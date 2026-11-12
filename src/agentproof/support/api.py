from fastapi import APIRouter, HTTPException

from .models import ProcessInput, ReviewInput, TicketInput, Upload
from .service import SupportError, SupportService


def create_router(service: SupportService):
    router = APIRouter(prefix="/api/support", tags=["SupportDesk"])

    def call(function, *args):
        try:
            return function(*args)
        except SupportError as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @router.get("/config")
    def config():
        return call(service.config)

    @router.get("/documents")
    def documents():
        return call(service.documents)

    @router.post("/documents", status_code=201)
    def add_document(value: Upload):
        return call(service.add_document, value.filename, value.content_base64)

    @router.get("/documents/{document_id}")
    def document(document_id: str):
        return call(service.document, document_id)

    @router.delete("/documents/{document_id}")
    def archive_document(document_id: str):
        return call(service.archive_document, document_id)

    @router.get("/tickets")
    def tickets():
        return call(service.tickets)

    @router.post("/tickets", status_code=201)
    def add_ticket(value: TicketInput):
        return call(service.add_ticket, value)

    @router.post("/tickets/import")
    def import_tickets(value: Upload):
        return call(service.import_tickets, value.filename, value.content_base64)

    @router.get("/tickets/{ticket_id}")
    def ticket(ticket_id: str):
        return call(service.ticket, ticket_id)

    @router.post("/tickets/{ticket_id}/process", status_code=202)
    def process(ticket_id: str, value: ProcessInput):
        return call(service.process, ticket_id, value)

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        return call(service.job, job_id)

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return call(service.cancel, job_id)

    @router.post("/tickets/{ticket_id}/review")
    def review(ticket_id: str, value: ReviewInput):
        return call(service.review, ticket_id, value)

    @router.get("/tickets/{ticket_id}/export")
    def export(ticket_id: str):
        return call(service.export, ticket_id)

    return router
