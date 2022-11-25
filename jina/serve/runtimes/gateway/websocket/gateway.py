import logging
import os
from typing import Optional

from jina.importer import ImportExtensions
from jina.serve.gateway import BaseGateway
from jina.serve.runtimes.gateway.websocket.app import get_fastapi_app


class WebSocketGateway(BaseGateway):
    """WebSocket Gateway implementation"""

    def __init__(
        self,
        ssl_keyfile: Optional[str] = None,
        ssl_certfile: Optional[str] = None,
        uvicorn_kwargs: Optional[dict] = None,
        proxy: Optional[bool] = None,
        **kwargs
    ):
        """Initialize the gateway
        :param ssl_keyfile: the path to the key file
        :param ssl_certfile: the path to the certificate file
        :param uvicorn_kwargs: Dictionary of kwargs arguments that will be passed to Uvicorn server when starting the server
        :param proxy: If set, respect the http_proxy and https_proxy environment variables, otherwise, it will unset
            these proxy variables before start. gRPC seems to prefer no proxy
        :param kwargs: keyword args
        """
        super().__init__(**kwargs)
        self.ssl_keyfile = ssl_keyfile
        self.ssl_certfile = ssl_certfile
        self.uvicorn_kwargs = uvicorn_kwargs

        if not proxy and os.name != 'nt':
            os.unsetenv('http_proxy')
            os.unsetenv('https_proxy')

    async def setup_server(self):
        """
        Setup WebSocket Server
        """
        from jina.helper import extend_rest_interface

        self.app = extend_rest_interface(
            get_fastapi_app(
                streamer=self.streamer,
                logger=self.logger,
                tracing=self.tracing,
                tracer_provider=self.tracer_provider,
            )
        )

        with ImportExtensions(required=True):
            from uvicorn import Config, Server

        if 'CICD_JINA_DISABLE_HEALTHCHECK_LOGS' in os.environ:

            class _EndpointFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    # NOTE: space is important after `GET /`, else all logs will be disabled.
                    return record.getMessage().find("GET / ") == -1

            # Filter out healthcheck endpoint `GET /`
            logging.getLogger("uvicorn.access").addFilter(_EndpointFilter())

        uvicorn_kwargs = self.uvicorn_kwargs or {}

        if self.ssl_keyfile and 'ssl_keyfile' not in uvicorn_kwargs.keys():
            uvicorn_kwargs['ssl_keyfile'] = self.ssl_keyfile

        if self.ssl_certfile and 'ssl_certfile' not in uvicorn_kwargs.keys():
            uvicorn_kwargs['ssl_certfile'] = self.ssl_certfile

        self.server = Server(
            config=Config(
                app=self.app,
                host=self.host,
                port=self.port,
                ws_max_size=1024 * 1024 * 1024,
                log_level=os.getenv('JINA_LOG_LEVEL', 'error').lower(),
                **uvicorn_kwargs,
            )
        )

    async def shutdown(self):
        """Free other resources allocated with the server, e.g, gateway object, ..."""
        self.server.should_exit = True
        await self.server.shutdown()

    async def run_server(self):
        """Run WebSocket server forever"""
        await self.server.serve()

    def _should_exit(self):
        """Determines if it should exit. This can be removed after https://github.com/encode/uvicorn/pull/1600/files
        is merged and released in uvicorn """
        return self.server.should_exit
