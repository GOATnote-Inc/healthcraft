"""Opt-in NeMo Gym adapter for the mechanical CC-022 roster fixture.

Requires the separately installed, pinned Gym SDK. No Gym dependency is added
to HEALTHCRAFT's default runtime. Uses Gym's Apache-2.0 resource-server API.
"""

from typing import ClassVar, Literal

from fastapi import HTTPException, Request
from nemo_gym.base_resources_server import (
    BaseResourcesServerConfig,
    BaseSeedSessionRequest,
    BaseSeedSessionResponse,
    BaseVerifyRequest,
    BaseVerifyResponse,
    ResourcesCloseSessionResponse,
    ReverifyMode,
    SimpleResourcesServer,
)
from nemo_gym.server_utils import SESSION_ID_KEY
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from healthcraft.integrations.nemo_roster import (
    FIXTURE_KEY,
    RosterSessions,
    SessionError,
    response_completion,
)


class RosterResourcesConfig(BaseResourcesServerConfig):
    REVERIFY_MODE: ClassVar[ReverifyMode] = ReverifyMode.UNSUPPORTED


class RosterSeedRequest(BaseSeedSessionRequest):
    # SimpleAgent.run sends its full request here. Extra expected answers are
    # ignored, never treated as fixture data or copied into server state.
    model_config = ConfigDict(extra="ignore")
    fixture_key: Literal["cc022-roster-source-retrieval/v1"]
    episode_id: StrictStr = Field(min_length=1)


class RosterSeedResponse(BaseSeedSessionResponse):
    resources_session_id: str
    episode_id: str
    fixture_key: str


class RosterVerifyRequest(BaseVerifyRequest):
    model_config = ConfigDict(extra="ignore")
    fixture_key: Literal["cc022-roster-source-retrieval/v1"]
    episode_id: StrictStr = Field(min_length=1)


class RosterVerifyResponse(BaseVerifyResponse):
    model_config = ConfigDict(extra="allow")


class RosterCloseRequest(BaseModel):
    # This optional component targets SimpleAgent's legacy seed/run protocol,
    # whose caller supplies one opaque string identity for the whole episode.
    model_config = ConfigDict(extra="forbid")
    resources_session_id: StrictStr = Field(min_length=1)
    episode_id: StrictStr = Field(min_length=1)


class SearchEncountersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: StrictStr | None = None
    date_from: StrictStr | None = None
    date_to: StrictStr | None = None
    chief_complaint: StrictStr | None = None
    esi_level: StrictInt | None = None
    disposition: StrictStr | None = None
    limit: StrictInt = 10


class EncounterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encounter_id: StrictStr


class PatientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: StrictStr


class RosterResourcesServer(SimpleResourcesServer):
    ray_enabled = False
    model_config = ConfigDict(arbitrary_types_allowed=True)
    config: RosterResourcesConfig
    sessions: RosterSessions = Field(default_factory=RosterSessions)

    def setup_webserver(self):
        app = super().setup_webserver()
        app.post("/searchEncounters")(self.search_encounters)
        app.post("/getEncounterDetails")(self.get_encounter_details)
        app.post("/getPatientHistory")(self.get_patient_history)
        return app

    def _session_id(self, request: Request) -> str:
        return request.session[SESSION_ID_KEY]

    async def seed_session(self, request: Request, body: RosterSeedRequest) -> RosterSeedResponse:
        try:
            data = self.sessions.seed(self._session_id(request), body.fixture_key, body.episode_id)
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RosterSeedResponse(**data)

    def _tool(self, request: Request, name: str, body: BaseModel) -> dict:
        try:
            return self.sessions.call(
                self._session_id(request), name, body.model_dump(exclude_unset=True)
            )
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def search_encounters(self, request: Request, body: SearchEncountersRequest) -> dict:
        return self._tool(request, "searchEncounters", body)

    async def get_encounter_details(self, request: Request, body: EncounterRequest) -> dict:
        return self._tool(request, "getEncounterDetails", body)

    async def get_patient_history(self, request: Request, body: PatientRequest) -> dict:
        return self._tool(request, "getPatientHistory", body)

    async def verify(self, request: Request, body: RosterVerifyRequest) -> RosterVerifyResponse:
        completion, reason = response_completion(body.response.model_dump(exclude_unset=True))
        try:
            result = self.sessions.verify(self._session_id(request), body.episode_id, completion)
        except SessionError as exc:
            result = {
                "fixture_key": FIXTURE_KEY,
                "reward": 0.0,
                "mechanical_passed": False,
                "execution_completed": False,
                "completion_status": "unknown",
                "benchmark_score": None,
                "benchmark_comparable": False,
                "grading_complete": False,
                "clinical_validation": "not_assessed",
                "mask_sample": True,
                "failure_kind": "session_lost",
                "failure_reason": str(exc),
                "certificate": None,
                "reward_scope": "mechanical_retrieval_only",
            }
        result["completion_reason"] = reason
        return RosterVerifyResponse(**(body.model_dump() | result))

    async def close_resources_session(
        self, request: Request, body: RosterCloseRequest
    ) -> ResourcesCloseSessionResponse:
        try:
            result = self.sessions.close(
                self._session_id(request), body.resources_session_id, body.episode_id
            )
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ResourcesCloseSessionResponse(**result)


if __name__ == "__main__":
    RosterResourcesServer.run_webserver()
