from enum import Enum


class CongestionState(Enum):
    SLOW_START = 1
    CONGESTION_AVOIDANCE = 2
    FAST_RECOVERY = 3


class CongestionController:
    def __init__(self):
        self.cwnd = 1.0
        self.ssthresh = 64.0
        self.duplicate_acks = 0
        self.state = CongestionState.SLOW_START
        self.last_ack = -1

    def ack_received(self, ack_number: int):
        if ack_number == self.last_ack:
            self.duplicate_ack()
            return

        self.last_ack = ack_number
        self.duplicate_acks = 0

        if self.state == CongestionState.FAST_RECOVERY:
            self.cwnd = self.ssthresh
            self.state = CongestionState.CONGESTION_AVOIDANCE
            return

        if self.state == CongestionState.SLOW_START:
            self.cwnd += 1.0
            if self.cwnd >= self.ssthresh:
                self.state = CongestionState.CONGESTION_AVOIDANCE
        else:
            self.cwnd += 1.0 / self.cwnd

    def duplicate_ack(self):
        self.duplicate_acks += 1

        if self.state != CongestionState.FAST_RECOVERY:
            if self.duplicate_acks == 3:
                self.ssthresh = max(self.cwnd / 2.0, 2.0)
                self.cwnd = self.ssthresh + 3.0
                self.state = CongestionState.FAST_RECOVERY
        else:
            self.cwnd += 1.0

    def timeout_occurred(self):
        self.ssthresh = max(self.cwnd / 2.0, 2.0)
        self.cwnd = 1.0
        self.state = CongestionState.SLOW_START
        self.duplicate_acks = 0
        self.last_ack = -1
