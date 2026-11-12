# Harbor API — account access

Example product policy, version 1. This is fictional demonstration material.

## Workspace invitations

Workspace invitations expire 72 hours after they are issued. An expired invitation
cannot be reactivated by the recipient. A workspace administrator can open
Settings > Members > Invite member and issue a new invitation to the same email.
The recipient should use the most recent invitation email. If the new invitation
is also rejected, collect the workspace name, the invitation's approximate issue
time and the exact error text, then escalate to account support.

## Single sign-on

For a workspace with enforced SSO, members must sign in through the organization's
identity provider. A password reset does not bypass enforced SSO. The workspace
administrator or the organization's IT team should check identity-provider access.
Support must not promise to disable SSO or change account permissions.

Never ask a customer for a password, API secret, full payment-card number, or
one-time security code. A draft must not claim an account was inspected unless an
actual authorized account lookup supplied that fact; this demo has no such lookup.
