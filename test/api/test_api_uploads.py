"""Resumable uploads with the tus protocol."""

import asyncio
import base64
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test.conftest import bearer, make_token

from cragradar_backend.core.settings import Settings
from cragradar_backend.ingest.staging import get_upload_path
from cragradar_backend.models.image import Image, ImageStatus

UPLOADS_PATH: str = "/api/uploads"
EDITOR_HEADERS: dict[str, str] = bearer(
    make_token(subject="editor-1", roles=("content_generator",))
)
TUS_HEADERS: dict[str, str] = {"Tus-Resumable": "1.0.0"}
CONTENT: bytes = bytes(range(256)) * 40


def encode_metadata(file_name: str) -> str:
    """Encode a file name as an ``Upload-Metadata`` header."""
    return "filename " + base64.b64encode(file_name.encode()).decode()


def create_upload(
    client: TestClient, length: int, headers: dict[str, str] = EDITOR_HEADERS
) -> Response:
    """Start an upload of ``length`` bytes named ``crag.jpg``."""
    return client.post(
        UPLOADS_PATH,
        headers={
            **headers,
            **TUS_HEADERS,
            "Upload-Length": str(length),
            "Upload-Metadata": encode_metadata("crag.jpg"),
        },
    )


def append(client: TestClient, upload_url: str, offset: int, chunk: bytes) -> Response:
    """Send one chunk of an upload at ``offset``."""
    return client.patch(
        upload_url,
        content=chunk,
        headers={
            **EDITOR_HEADERS,
            **TUS_HEADERS,
            "Upload-Offset": str(offset),
            "Content-Type": "application/offset+octet-stream",
        },
    )


def read_image(session_factory: async_sessionmaker[AsyncSession], image_id: uuid.UUID) -> Image:
    """Read an image row from the test database."""

    async def read() -> Image:
        """Read the row in a new session."""
        async with session_factory() as session:
            image: Image | None = await session.get(Image, image_id)
            assert image is not None
            return image

    return asyncio.run(read())


@pytest.fixture
def upload_url(api_client: TestClient) -> str:
    """Start an upload of ``CONTENT`` and give its URL."""
    return str(create_upload(api_client, length=len(CONTENT)).headers["Location"])


def get_image_id(upload_url: str) -> uuid.UUID:
    """Get the image id at the end of an upload URL."""
    return uuid.UUID(upload_url.rsplit("/", 1)[1])


def test_options_describes_tus_capabilities(api_client: TestClient) -> None:
    """Check that the version, extensions and maximum size are announced."""
    response: Response = api_client.options(UPLOADS_PATH)

    assert response.status_code == 204
    assert response.headers["Tus-Version"] == "1.0.0"
    assert response.headers["Tus-Extension"] == "creation"
    assert response.headers["Tus-Max-Size"] == "10000000"


def test_create_registers_an_uploading_image(
    api_client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Check that creating an upload answers its URL and records the image."""
    response: Response = create_upload(api_client, length=len(CONTENT))

    assert response.status_code == 201
    image: Image = read_image(session_factory, get_image_id(response.headers["Location"]))
    assert image.status == ImageStatus.UPLOADING
    assert image.file_name == "crag.jpg"
    assert image.created_by == "editor-1"


def test_viewer_cannot_upload(api_client: TestClient) -> None:
    """Check that a user without a content role is answered 403."""
    viewer_headers: dict[str, str] = bearer(make_token(roles=("viewer",)))
    assert create_upload(api_client, length=10, headers=viewer_headers).status_code == 403


def test_anonymous_user_cannot_upload(api_client: TestClient) -> None:
    """Check that a request without token is answered 401."""
    assert create_upload(api_client, length=10, headers={}).status_code == 401


def test_too_large_upload_is_rejected(api_client: TestClient) -> None:
    """Check that an upload above ``max_size_bytes`` is answered 413."""
    assert create_upload(api_client, length=10_000_001).status_code == 413


def test_other_tus_version_is_rejected(api_client: TestClient) -> None:
    """Check that another tus version is answered 412."""
    response: Response = api_client.post(
        UPLOADS_PATH, headers={**EDITOR_HEADERS, "Tus-Resumable": "0.2.2", "Upload-Length": "10"}
    )
    assert response.status_code == 412


def test_upload_in_chunks_completes_the_image(
    api_client: TestClient,
    upload_url: str,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Check that two chunks reassemble the file and queue the image for the worker."""
    middle: int = 4000
    first_response: Response = append(api_client, upload_url, 0, CONTENT[:middle])
    second_response: Response = append(api_client, upload_url, middle, CONTENT[middle:])

    assert first_response.headers["Upload-Offset"] == str(middle)
    assert second_response.status_code == 204
    assert second_response.headers["Upload-Offset"] == str(len(CONTENT))
    image_id: uuid.UUID = get_image_id(upload_url)
    assert read_image(session_factory, image_id).status == ImageStatus.UPLOADED
    upload_path: Path = get_upload_path(settings.upload.staging_root, image_id)
    assert upload_path.read_bytes() == CONTENT


def test_head_reports_the_offset_to_resume_from(api_client: TestClient, upload_url: str) -> None:
    """Check that ``HEAD`` tells how many bytes were received."""
    append(api_client, upload_url, 0, CONTENT[:1000])

    response: Response = api_client.head(upload_url, headers={**EDITOR_HEADERS, **TUS_HEADERS})

    assert response.status_code == 200
    assert response.headers["Upload-Offset"] == "1000"
    assert response.headers["Upload-Length"] == str(len(CONTENT))
    assert response.headers["Cache-Control"] == "no-store"


def test_wrong_offset_conflicts(api_client: TestClient, upload_url: str) -> None:
    """Check that a chunk at another offset than the received size is answered 409."""
    response: Response = append(api_client, upload_url, 500, CONTENT[:100])

    assert response.status_code == 409
    assert response.headers["Upload-Offset"] == "0"


def test_body_past_declared_length_is_rejected(api_client: TestClient, upload_url: str) -> None:
    """Check that bytes beyond ``Upload-Length`` are answered 413 and not kept."""
    response: Response = append(api_client, upload_url, 0, CONTENT + b"extra")

    assert response.status_code == 413
    head: Response = api_client.head(upload_url, headers={**EDITOR_HEADERS, **TUS_HEADERS})
    assert head.headers["Upload-Offset"] == "0"


def test_wrong_content_type_is_rejected(api_client: TestClient, upload_url: str) -> None:
    """Check that a chunk without the tus content type is answered 415."""
    response: Response = api_client.patch(
        upload_url,
        content=b"data",
        headers={**EDITOR_HEADERS, **TUS_HEADERS, "Upload-Offset": "0"},
    )
    assert response.status_code == 415


def test_upload_of_another_user_is_hidden(api_client: TestClient, upload_url: str) -> None:
    """Check that another content editor cannot see nor resume the upload."""
    other_editor_headers: dict[str, str] = bearer(
        make_token(subject="editor-2", roles=("content_generator",))
    )
    response: Response = api_client.head(
        upload_url, headers={**other_editor_headers, **TUS_HEADERS}
    )
    assert response.status_code == 404


def test_complete_upload_cannot_be_appended(api_client: TestClient, upload_url: str) -> None:
    """Check that a chunk sent after the last one is answered 409."""
    append(api_client, upload_url, 0, CONTENT)
    assert append(api_client, upload_url, len(CONTENT), b"more").status_code == 409
