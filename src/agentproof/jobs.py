"""Single-host durable queue. Queued jobs survive; interrupted trials are not resumed."""

import fcntl
import logging
import threading
from pathlib import Path

from .store import Store


class ExperimentWorker:
    def __init__(self, store: Store, execute):
        self.store = store
        self.execute = execute
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = None
        self.lease = None

    @property
    def available(self):
        return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("This experiment worker is already running")
        self.stop_event.clear()
        self.wake_event.clear()
        # flock is released by the OS on process death; no expiry race can create two owners.
        # Resolve aliases so symlinked database paths share a lease. SQLite is single-host here.
        lease_path = str(Path(self.store.path).resolve()) + ".worker.lock"
        self.lease = open(lease_path, "a+")  # noqa: SIM115 - held until the worker exits
        try:
            fcntl.flock(self.lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lease.close()
            self.lease = None
            raise RuntimeError(
                "An AgentProof worker already owns this database. Run one API process per database."
            ) from None
        try:
            self.store.fail_interrupted_jobs()
            self.thread = threading.Thread(
                target=self._run, name="agentproof-experiment-worker", daemon=True
            )
            self.thread.start()
        except BaseException:
            self._release()
            raise

    def wake(self):
        self.wake_event.set()

    def _release(self):
        if self.lease is not None:
            fcntl.flock(self.lease.fileno(), fcntl.LOCK_UN)
            self.lease.close()
            self.lease = None

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.wake_event.clear()
                experiment = self.store.claim_experiment()
                if experiment is None:
                    self.wake_event.wait(0.25)
                    continue
                try:
                    self.execute(experiment, self.stop_event)
                except Exception as exc:  # noqa: BLE001 - isolate failures between queued jobs
                    # A broken executor must not strand the rest of the durable queue.
                    # Persist/log only the class, never exception text that may contain secrets.
                    self.store.finish_experiment(
                        experiment["id"],
                        "failed",
                        {
                            "type": type(exc).__name__,
                            "message": "The worker could not execute this experiment. Partial evidence is preserved; inspect the runtime before retrying.",
                        },
                    )
        except Exception as exc:  # noqa: BLE001 - worker boundary, expose unavailable state
            logging.getLogger(__name__).error("Experiment worker stopped: %s", type(exc).__name__)
        finally:
            self._release()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        # Wait for the current bounded trial; release the lease only after execution stops.
        if self.thread is not None:
            self.thread.join()
