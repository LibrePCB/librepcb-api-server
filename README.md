# librepcb-api-server

Official server-side implementation of the
[LibrePCB API](https://developers.librepcb.org/d1/dcb/doc_server_api.html)
as accessed by the LibrePCB application. Note that some older API paths are
implemented in a different way and might be migrated to this repository
later.

## Requirements

Only Docker Compose is needed to run this server on a Linux machine.

## Configuration

To make all features working, some environment variables are required. For
this, you can add a `.env` file with the following content and add your
credentials:

```
DIGIKEY_CLIENT_ID=
DIGIKEY_CLIENT_SECRET=
```

## Usage

For local development, the server can be run with this command:

```bash
./docker-compose.sh up --build
```

Afterwards, the API runs on http://localhost:8000/:

```bash
curl -X POST -H "Content-Type: application/json" -d @testdata/request.json \
     'http://localhost:8000/api/v1/parts/query' | jq '.'
```

## Development

To format & check Python files, use UV and Ruff:

```bash
uv run ruff format
uv run ruff check
```

## License

The content in this repository is published under the
[GNU GPLv3](http://www.gnu.org/licenses/gpl-3.0.html) license.
