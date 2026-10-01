# Errors: Python

- Catch-all handlers: `except Exception` returns the fixed string `"Internal Server Error"`.
- Batch/loop failure aggregation: `logger.error('... %d failed: %s', failed_count, {id: message})`.
- Message style: `raise NotFoundError(f'Campaign request not found: id={request_id}')`.
- Timeouts: Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`.
