"""Flow Control.

States:

New messages:
    mark_position    writer -> sender (has an ID)
    report position  sender -> writer
    read data        writer -> sender (go read this data for me)

Thresholds:
    Threshold_High_MaxOutstandingData       - When above this, stop sending requests to sender
    Threshold_Mid_StartSendingReadRequests - When below this, start sending read requests
    Threshold_Low_RestartSendingData       - When below this, start sending normal records

State machine:
    FORWARDING  - Streaming every record to the sender in memory
      -> PAUSED when oustanding_data > Threshold_High_MaxOutstandingData
    PAUSING  - Writing records to disk and waiting for sender to drain
      -> RECOVERING when outstanding_data < Threshold_Mid_StartSendingReadRequests
    RECOVERING - Recovering from disk and waiting for sender to drain
      -> FORWARDING when outstanding_data < Threshold_Low_RestartSendingData

"""

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from wandb.proto import wandb_internal_pb2 as pb
from wandb.proto import wandb_telemetry_pb2 as tpb
from wandb.sdk.lib import fsm, telemetry

from .settings_static import SettingsStatic

if TYPE_CHECKING:
    from wandb.proto.wandb_internal_pb2 import Record

logger = logging.getLogger(__name__)


def _get_request_type(record: "Record") -> Optional[str]:
    record_type = record.WhichOneof("record_type")
    if record_type != "request":
        return None
    request_type = record.request.WhichOneof("request_type")
    return request_type


def _is_control_record(record: "Record") -> bool:
    request_type = _get_request_type(record)
    if request_type not in {"sender_mark_report"}:
        return False
    return True


class FlowControl:
    _settings: SettingsStatic
    _forward_record: Callable[[Any, "Record"], None]
    _write_record: Callable[[Any, "Record"], int]
    _ensure_flushed: Callable[[Any, int], None]

    _track_last_written_offset: int
    _track_last_forwarded_offset: int
    _track_first_unforwarded_offset: int
    _track_last_flushed_offset: int
    _track_recovering_requests: int

    _telemetry_obj: tpb.TelemetryRecord
    _telemetry_overflow: bool
    _fsm: fsm.Fsm["Record"]

    def __init__(
        self,
        settings: SettingsStatic,
        forward_record: Callable[["Record"], None],
        write_record: Callable[["Record"], int],
        ensure_flushed: Callable[["int"], None],
    ) -> None:
        self._settings = settings
        self._forward_record = forward_record  # type: ignore
        self._write_record = write_record  # type: ignore
        self._ensure_flushed = ensure_flushed  # type: ignore

        # thresholds to define when to PAUSE, RESTART, FORWARDING
        self._threshold_block_high = 128  # 4MB
        self._threshold_block_mid = 64  # 2MB
        self._threshold_block_low = 16  # 512kB
        self._mark_granularity_blocks = 2  # 64kB

        # track last written request
        self._track_last_written_offset = 0

        # periodic probes sent to the sender to find out how backed up we are
        self._mark_write_offset_sent = 0
        self._mark_write_offset_reported = 0

        self._telemetry_obj = tpb.TelemetryRecord()
        self._telemetry_overflow = False

        # State machine definition
        fsm_table: fsm.FsmTable[Record] = {
            StateForwarding: [(self._should_pause, StatePausing)],
            StatePausing: [(self._should_recover, StateRecovering)],
            StateRecovering: [(self._should_forward, StateForwarding)],
        }
        self._fsm = fsm.Fsm(
            states=[StateForwarding(self), StatePausing(self), StateRecovering(self)],
            table=fsm_table,
        )

    def _telemetry_record_overflow(self) -> None:
        if self._telemetry_overflow:
            return
        self._telemetry_overflow = True
        with telemetry.context(obj=self._telemetry_obj) as tel:
            tel.feature.flow_control_overflow = True
        record = pb.Record()
        record.telemetry.CopyFrom(self._telemetry_obj)
        self._forward_record(record)

    def _process_record(self, record: "Record") -> None:
        request_type = _get_request_type(record)
        if request_type == "sender_mark_report":
            self._process_sender_mark_report(record)

    def _process_sender_mark_report(self, record: "Record") -> None:
        mark_id = record.request.sender_mark_report.mark_id
        self._mark_write_offset_reported = mark_id

    def _process_report_sender_position(self, record: "Record") -> None:
        pass

    def _send_mark(self) -> None:
        record = pb.Record()
        request = pb.Request()
        last_write_offset = self._track_last_written_offset
        sender_mark = pb.SenderMarkRequest(mark_id=last_write_offset)
        request.sender_mark.CopyFrom(sender_mark)
        record.request.CopyFrom(request)
        self._forward_record(record)
        self._mark_sent_write_offset = last_write_offset

    def _maybe_send_mark(self) -> None:
        """Send mark if we are writting the first record in a block."""
        # if self._last_block_end == self._written_block_end:
        #     return
        self._send_mark()

    def _maybe_request_read(self) -> None:
        pass
        # if we are paused
        # and more than one chunk has been written
        # and N time has elapsed
        # send message asking sender to read from last_read_offset to current_offset

    def _behind_bytes(self) -> int:
        behind_bytes = self._mark_write_offset_sent - self._mark_write_offset_reported
        return behind_bytes

    def flush(self) -> None:
        pass

    def _should_pause(self, inputs: "Record") -> bool:
        if self._behind_bytes() < self._threshold_block_high:
            return False
        return True

    def _should_recover(self, inputs: "Record") -> bool:
        return False

    def _should_forward(self, inputs: "Record") -> bool:
        return False

    def send_with_flow_control(self, record: "Record") -> None:
        self._process_record(record)

        if not _is_control_record(record):
            offset = self._write_record(record)
            self._track_last_written_offset = offset

        self._fsm.run(record)


class StateForwarding:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return
        self._flow._forward_record(record)
        self._flow._maybe_send_mark()


class StatePausing:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def enter(self, record: "Record") -> None:
        self._flow._telemetry_record_overflow()
        self._flow._send_mark()

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return


class StateRecovering:
    def __init__(self, flow: FlowControl) -> None:
        self._flow = flow

    def run(self, record: "Record") -> None:
        if _is_control_record(record):
            return
