# v0.2.18
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *

import json
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# DeFiRiskGate -- a worked example of consuming ReputationOracle.
#
# A DeFi protocol deposits collateral against a counterparty's reputation.
# If the counterparty's reputation drops below a threshold -- audit failures,
# regulatory actions, community trust collapse -- the gate opens and
# depositors can withdraw their funds.
#
# The point of the example is what this contract does *not* contain: no web
# fetching, no prompts, no equivalence principles, no signal handling. It
# implements one callback and reads one score integer. All of the
# assessment machinery lives in ReputationOracle.
#
# Deploy order:
#   1. deploy ReputationOracle
#   2. profile_id = oracle.create_profile(entity_name, url, criteria, ...)
#   3. deploy DeFiRiskGate(oracle_address, profile_id, counterparty)
#   4. oracle.subscribe(profile_id, alert_below=3)  -- called *by* the gate
# ---------------------------------------------------------------------------


SCORE_MIXED = 3

ERR_EXPECTED = "EXPECTED"


@allow_storage
@dataclass
class Alert:
    version: u32
    old_score: u8
    new_score: u8
    summary: str


@gl.contract_interface
class IReputationOracle:
    class View:
        def get_profile(self, profile_id: u256) -> dict: ...

    class Write:
        def subscribe(self, profile_id: u256, alert_below: int) -> None: ...


class WithdrawalUnlocked(gl.Event):
    def __init__(self, version: u32, new_score: u8, /, **blob): ...


class DeFiRiskGate(gl.Contract):
    oracle: Address
    profile_id: u256
    counterparty: Address
    depositor: Address
    withdrawal_unlocked: bool
    score_threshold: u8
    alerts: DynArray[Alert]

    def __init__(
        self,
        oracle: Address,
        profile_id: u256,
        counterparty: Address,
        score_threshold: int = SCORE_MIXED,
    ):
        self.oracle = oracle
        self.profile_id = profile_id
        self.counterparty = counterparty
        self.depositor = gl.message.sender_address
        self.withdrawal_unlocked = False
        self.score_threshold = u8(score_threshold)

    # -- the entire integration surface -------------------------------------

    @gl.public.write
    def on_reputation_change(
        self,
        profile_id: u256,
        version: u32,
        old_score: u8,
        new_score: u8,
        confidence: u8,
        summary: str,
        diff_json: str,
    ) -> None:
        """Callback invoked by ReputationOracle on a reputation change.

        Two checks matter here:
        1. The caller must be the oracle we trust.
        2. The change must concern the profile we subscribed to.
        Without both, anyone could unlock the withdrawal.
        """
        if gl.message.sender_address != self.oracle:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: caller is not the oracle")
        if profile_id != self.profile_id:
            raise gl.vm.UserError(f"{ERR_EXPECTED}: unexpected profile id")

        record = self.alerts.append_new_get()
        record.version = version
        record.old_score = old_score
        record.new_score = new_score
        record.summary = summary

        if int(new_score) < int(self.score_threshold):
            self.withdrawal_unlocked = True
            WithdrawalUnlocked(version, new_score, summary=str(summary)).emit()

    # -- views --------------------------------------------------------------

    @gl.public.view
    def is_withdrawal_unlocked(self) -> bool:
        return bool(self.withdrawal_unlocked)

    @gl.public.view
    def get_alerts(self) -> list:
        return [
            {
                "version": int(a.version),
                "old_score": int(a.old_score),
                "new_score": int(a.new_score),
                "summary": str(a.summary),
            }
            for a in self.alerts
        ]

    @gl.public.view
    def get_counterparty_reputation(self) -> dict:
        """Read the upstream profile directly."""
        return IReputationOracle(self.oracle).view().get_profile(self.profile_id)
