# Harbor API — webhook delivery and verification

Example product documentation, version 1. This is fictional demonstration material.

## Verify a delivery

Harbor sends an X-Harbor-Signature header containing a hexadecimal HMAC-SHA256
signature. Calculate HMAC-SHA256 over the original, unmodified request-body bytes
using the endpoint's signing secret, then compare signatures in constant time.
Parsing and reserializing JSON before verification can change the bytes and cause
signature verification to fail. After rotating a signing secret, update the
receiver's configured secret. Do not ask a customer to send the secret in a ticket.

## Responses and retries

Any 2xx response acknowledges successful delivery. Delivery attempts receiving 429
or 5xx responses are retried after 1 minute, 5 minutes and 30 minutes. A 401 response
is not retried: first check the configured signing secret and verification of the
original request-body bytes. A 410 response disables the endpoint.

For unresolved failures, request the delivery ID, response status, approximate
timestamp and a redacted error message. Do not claim a delivery was replayed or
an endpoint was repaired: this workspace does not execute those customer actions.
