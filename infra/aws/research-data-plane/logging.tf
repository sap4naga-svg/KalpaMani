# CloudWatch Logs -- bounded, and never a destination for data or credentials.
#
# A log group is a durable, queryable, long-lived store. Anything written here
# survives the task, survives the container, and is searchable afterwards. That
# makes it the single most consequential place for a redaction failure to land.
#
# TWO RULES, BOTH BINDING ON THE CODE THAT WRITES HERE (ADR-0007 §8):
#
#   1. NO VENDOR PAYLOAD IS EVER LOGGED. Not a sample row, not "the first record
#      for debugging", not an error message that embeds the response body. A
#      payload in CloudWatch is a copy of licensed data in a store the deletion
#      runbook has to find (deletion runbook step 12).
#
#   2. NO SECRET AND NO FULL PROVIDER URL IS EVER LOGGED. The leading provider
#      candidate accepts its API key as a QUERY PARAMETER, so the key is part of
#      every request URL -- and unhandled exceptions, retry logging and HTTP debug
#      logging all print URLs by default. Query strings are redacted at the
#      logging boundary, and exceptions are sanitized before they propagate.
#
# Retention is bounded and cannot be set to "never expire" -- see the validation
# on `log_retention_days`. Unbounded retention turns any redaction failure into a
# permanent one.

resource "aws_cloudwatch_log_group" "research" {
  name              = "/kalpamani/${var.name_prefix}/research"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.name_prefix}-research"
  }
}
