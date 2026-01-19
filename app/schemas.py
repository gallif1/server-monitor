from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

# Define allowed protocol values (matches the DB ENUM)
ProtocolType = Literal["HTTP", "HTTPS", "FTP", "SSH"]

# Define allowed health status values (matches the DB ENUM)
HealthStatusType = Literal["UNKNOWN", "HEALTHY", "UNHEALTHY"]

# Model used when creating a new server (input from client)
class ServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    protocol: ProtocolType

# Model used when updating an existing server
# All fields are optional
class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    protocol: ProtocolType | None = None

# Model used when returning server data to the client (output schema)
class ServerOut(BaseModel):
    id: int
    name: str
    url: str
    protocol: ProtocolType
    health_status: HealthStatusType
    created_at: datetime
    updated_at: datetime

class RequestOut(BaseModel):
    id: int
    server_id: int
    checked_at: datetime
    is_success: bool
    latency_ms: int
    http_status: int | None = None
    error: str | None = None


class ServerWithLastRequests(ServerOut):
    last_requests: list[RequestOut]

class WasHealthyOut(BaseModel):
    server_id: int
    timestamp: datetime
    status: HealthStatusType
