"""Vendor-neutral reference client for the local JSON Lines agent protocol.

This is the adapter an external programming agent is expected to wrap, not a new
service.  It speaks exactly the envelope ``agent_bridge.AgentBridge.dispatch``
already accepts, so any host that can write a UTF-8 line to a process and read
one back can drive the project without a vendor SDK:

* ``LoopbackTransport`` drives an in-process bridge (used by the contract tests).
* ``StreamTransport`` drives a real ``agent-serve`` process over its stdio pipes.

Nothing here re-implements rule logic, spawns paid resources, or knows about a
specific provider.  The module is deliberately thin: envelope validation,
request-id bookkeeping, error mapping, and two small read-only helpers that turn
raw monitor snapshots into the answers an agent actually needs (which task can be
resumed, which hardware metric was simply never collected).
"""

import json
import re
from typing import Protocol
from uuid import uuid4

PROTOCOL = "ygo-kito-local-json-v1"
TRANSPORT = "json-lines-not-mcp"
SCHEMA_VERSION = 1

REQUEST_FIELDS = {"schema_version", "id", "method", "params"}
RESPONSE_FIELDS = {"schema_version", "id", "ok", "error", "result"}

#: States a ``training.control`` operation can continue directly.
RESUMABLE_STATES = ("created", "paused")

#: States that must go through ``training.recover`` before any resume attempt.
#: Reporting these as "resumable" would send a host straight into a control
#: operation the server refuses, because ``resume`` is only valid from ``paused``.
RECOVERABLE_STATES = ("failed",)

#: The step each candidate state needs, and which RPC performs it.
#: ``training.control`` takes an operation; ``training.recover`` does not.
NEXT_STEP = {"created": ("training.control", "start"),
             "paused": ("training.control", "resume"),
             "failed": ("training.recover", None)}

#: Hardware/throughput metrics an operating agent wants.  ``RunMonitor``
#: allowlists the names; ``RunReporter`` does not currently produce all of them.
REQUIRED_METRICS = ("elapsed_seconds", "samples_per_second", "cpu_percent",
                    "rss_bytes", "gpu_memory_bytes")

#: What a host process must be able to do before it can use each role.
#: Capability statements, not brand requirements.
HOST_CAPABILITIES = {
    "read": ("read project files granted to the host",
             "spawn a local process and speak UTF-8 JSON Lines to its stdio",
             "keep request IDs so a retry is distinguishable from a new attempt"),
    "control": ("everything required for read",
                "be explicitly granted training-control authority by the operator",
                "accept that no cloud/paid resource is started by default"),
    "opponent": ("read the local protocol documentation",
                 "submit only action IDs offered in the current window",
                 "tolerate a rejected stale window without inventing a move"),
}


class ProtocolError(RuntimeError):
    """The local wire format is wrong: bad JSON, wrong envelope, mismatched ID."""


class RemoteError(RuntimeError):
    """The bridge answered with ``ok: false``.  Carries its stable error code."""

    def __init__(self, code, message, request_id=None):
        self.code, self.message, self.request_id = code, message, request_id
        super().__init__(f"{code}: {message}")


#: The server accepts ids matching this rule; method names contain dots, so a
#: method name can never be used as an id verbatim.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def check_request_id(value):
    """Reject an id the server would refuse, before it costs a round trip."""
    if not isinstance(value, str) or not REQUEST_ID_PATTERN.fullmatch(value):
        raise ProtocolError("request id must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}")
    return value


def request_id_for(method):
    """A fresh id derived from the method name.

    Unique per call, so two independent clients never collide on the same id by
    accident.  An id that must be reused for a retry has to be supplied by the
    caller instead of generated here.
    """
    safe = "".join(character if character.isalnum() or character in "_-" else "-"
                   for character in method)[:40]
    return check_request_id(f"{safe}-{uuid4().hex[:12]}")


def request(method, params=None, request_id=None):
    """Build one request envelope.

    ``request_id`` is used verbatim when given: that is how a retry addresses the
    same logical operation instead of creating a second one.
    """
    if not isinstance(method, str) or not method:
        raise ProtocolError("method must be a nonempty string")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError("params must be an object")
    if request_id is None:
        request_id = request_id_for(method)
    return {"schema_version": SCHEMA_VERSION, "id": check_request_id(request_id),
            "method": method, "params": params}


def parse_response(value, request_id=None):
    """Validate one response envelope and return its ``result``.

    Accepts a mapping or a JSON string.  Rejects unknown envelope fields so a
    future protocol addition cannot be silently ignored by an old host.
    """
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProtocolError("response is not valid JSON") from error
    if not isinstance(value, dict):
        raise ProtocolError("response must be an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported response schema version")
    unknown = set(value) - RESPONSE_FIELDS
    if unknown:
        raise ProtocolError("unexpected response fields: " + ", ".join(sorted(unknown)))
    if request_id is not None and value.get("id") != request_id:
        raise ProtocolError("response id does not match the request")
    if value.get("ok") is True:
        if "error" in value:
            raise ProtocolError("a successful response must not carry an error")
        return value.get("result")
    if value.get("ok") is False:
        error = value.get("error")
        if not isinstance(error, dict) or set(error) != {"code", "message"}:
            raise ProtocolError("an error response needs exactly code and message")
        raise RemoteError(error["code"], error["message"], value.get("id"))
    raise ProtocolError("response ok must be a boolean")


class Transport(Protocol):
    def exchange(self, message: dict) -> dict: ...


class LoopbackTransport:
    """In-process transport over a ``dispatch``-shaped callable.

    ``dispatch`` is the same entry the stdio server uses, so a contract test here
    exercises the production request path rather than a parallel implementation.
    """

    def __init__(self, dispatch):
        if not callable(dispatch):
            raise ProtocolError("loopback transport needs a dispatch callable")
        self.dispatch = dispatch
        self.exchanges = 0

    def exchange(self, message):
        self.exchanges += 1
        return self.dispatch(message)


class StreamTransport:
    """Newline-delimited JSON over two text streams (a live ``agent-serve``).

    Flushes after every request; a short read means the peer closed, which is
    reported rather than retried, because the peer owns the native lease.
    """

    def __init__(self, source, destination):
        self.source, self.destination = source, destination

    def exchange(self, message):
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            self.destination.write(payload)
            self.destination.flush()
        except UnicodeEncodeError as error:
            raise ProtocolError("destination stream cannot carry the request as UTF-8") from error
        try:
            line = self.source.readline()
        except UnicodeDecodeError as error:
            # A text wrapper raises during readline(), before any parsing; the
            # decode failure belongs to the transport, not to the caller.
            raise ProtocolError("source stream is not valid UTF-8") from error
        if not line:
            raise ProtocolError("peer closed the connection without answering")
        try:
            return json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            # A malformed line is a wire-format failure, not a crash: every
            # transport-level problem surfaces as ProtocolError.
            raise ProtocolError("peer sent a line that is not valid JSON") from error


class Client:
    """Thin typed client.  Every call returns a plain JSON value or raises.

    Default request IDs are unique per call, so a new ``Client`` cannot collide
    with an earlier one.  For an operation that may be retried (above all
    ``training_control``), pass the *same* ``request_id`` again: the server keys
    idempotency on that id, and a fresh id would be treated as a second attempt.
    """

    def __init__(self, transport):
        self.transport = transport
        self._counter = 0
        self._token = uuid4().hex[:8]
        self._capabilities = None

    def call(self, method, params=None, request_id=None):
        self._counter += 1
        if request_id is None:
            safe = "".join(character if character.isalnum() or character in "_-" else "-"
                           for character in method)[:40]
            request_id = f"{safe}-{self._token}-{self._counter}"
        message = request(method, params, request_id)
        return parse_response(self.transport.exchange(message), message["id"])

    def capabilities(self):
        if self._capabilities is None:
            self._capabilities = self.call("capabilities")
        return self._capabilities

    def has(self, method):
        return method in self.capabilities().get("methods", ())

    # -- monitoring -------------------------------------------------------
    def runs(self):
        return self.call("runs.list")

    def run(self, run_id):
        return self.call("runs.read", {"run_id": run_id})

    def metrics(self, run_id):
        return self.call("runs.metrics", {"run_id": run_id})

    def checkpoint(self, run_id, checkpoint_id):
        return self.call("checkpoints.read", {"run_id": run_id, "checkpoint_id": checkpoint_id})

    def resumable_runs(self):
        """Continuable runs, each with the step it actually needs.

        ``created`` and ``paused`` are directly continuable, by a
        ``training.control`` operation.  ``failed`` is **not**: it has to pass
        through ``training.recover`` first, so it is still listed (dropping it
        would hide work that needs recovery) but with ``resumable: False`` and
        ``requires_recovery: True``.  This is the read-only half of task
        continuation: it never starts anything.
        """
        found = []
        for run in self.runs():
            state = run.get("state")
            if state not in NEXT_STEP or not run.get("checkpoint_ids"):
                continue
            method, operation = NEXT_STEP[state]
            found.append({"run_id": run["run_id"], "state": state, "revision": run["revision"],
                          "checkpoint_ids": list(run["checkpoint_ids"]), "source": run["source"],
                          "expected_revision": run["revision"],
                          "resumable": state in RESUMABLE_STATES,
                          "requires_recovery": state in RECOVERABLE_STATES,
                          "next_step": {"method": method, "operation": operation}})
        return sorted(found, key=lambda item: (item["run_id"], item["revision"]), reverse=True)

    # -- decks and environments ------------------------------------------
    def environment_register(self, environment):
        return self.call("environment.register", environment)

    def environment_runtime(self):
        return self.call("environment.runtime")

    def deck_import(self, deck_id, environment_id, content, *, source="user_provided", format="ydk"):
        return self.call("deck.import", {"deck_id": deck_id, "environment_id": environment_id,
                                         "source": source, "format": format, "content": content})

    def deck_read(self, deck_id):
        return self.call("deck.read", {"deck_id": deck_id})

    def metric_gaps(self, run_id):
        """Convenience wrapper that takes the run id, not the metrics object.

        ``runs.metrics`` returns a record with the readings nested under
        ``metrics``; passing that record straight to ``metric_gaps`` would report
        every collected reading as absent.
        """
        snapshot = self.metrics(run_id)
        if not isinstance(snapshot, dict) or "metrics" not in snapshot:
            raise ProtocolError("runs.metrics did not return a metrics object")
        return metric_gaps(snapshot["metrics"])

    # -- authorised control ----------------------------------------------
    def training_control(self, run_id, operation, expected_revision, request_id=None):
        """Start/pause/resume/stop/save within the granted authority.

        Retry with the same ``request_id``: that is what makes the server return
        the cached outcome instead of reserving a second operation.
        """
        if request_id is None:
            request_id = request_id_for("training.control")
        return self.call("training.control", {"run_id": run_id, "operation": operation,
                                              "expected_revision": expected_revision},
                         request_id=request_id)


def metric_gaps(metrics):
    """Split a snapshot's metrics into collected and never-collected.

    An absent hardware metric means "the trainer did not sample it", which is not
    the same as zero.  Callers use this to print ``unknown`` instead of ``0``.
    """
    if not isinstance(metrics, dict):
        raise ProtocolError("metrics must be an object")
    if "metrics" in metrics or "run_id" in metrics:
        # Handed the run record instead of its readings.  Silently answering
        # "everything missing" would misreport collected data as absent.
        raise ProtocolError("expected the snapshot's metrics object, got the run record; "
                            "call metric_gaps(snapshot['metrics']) or Client.metric_gaps(run_id)")
    present = [key for key in REQUIRED_METRICS if key in metrics]
    absent = [key for key in REQUIRED_METRICS if key not in metrics]
    return {"present": present, "absent": absent,
            "note": "absent means not collected in this snapshot; do not render it as zero"}
