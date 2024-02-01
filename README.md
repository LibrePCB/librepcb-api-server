# librepcb-api-server

Official server-side implementation of the
[LibrePCB API](https://developers.librepcb.org/d1/dcb/doc_server_api.html)
as accessed by the LibrePCB application. Note that some older API paths are
implemented in a different way and might be migrated to this repository
later.

## Requirements

Only Docker Compose is needed to run this server on a Linux machine.

## Configuration

To make all features working, a configuration file `config/api.json` is
required with the following content:

```json
{
     /* Config for endpoint '/parts' */
     "parts_operational": false,
     "parts_query_url": "",
     "parts_query_token": ""
}
```

## Usage

For local development, the server can be run with this command:

```bash
docker-compose up --build
```

Afterwards, the API runs on http://localhost:8000/:

```bash
curl -X POST -H "Content-Type: application/json" -d @demo-request.json \
     'http://localhost:8000/api/v1/parts/query' | jq '.'
```

## License

The content in this repository is published under the
[GNU GPLv3](http://www.gnu.org/licenses/gpl-3.0.html) license.
