"""Range downloads read the verified descriptor, not a later-opened path."""
import os
from secrets import token_hex

import anyio
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, MalformedRangeHeader, RangeNotSatisfiable

from packages.runtime.artifact_identity import ArtifactIdentityError, file_identity


class VerifiedArtifactResponse(FileResponse):
    def __init__(self, path, identity, **kwargs):
        super().__init__(path, **kwargs)
        self.identity = identity['descriptor_identity']
        self.path_identity = identity['identity']

    async def __call__(self, scope, receive, send):
        try:
            file = await anyio.open_file(self.path, 'rb')
        except OSError:
            return await JSONResponse({'detail': 'ARTIFACT_CHANGED: 产物已不可读取'}, status_code=409)(scope, receive, send)
        async with file:
            try:
                info = await anyio.to_thread.run_sync(os.fstat, file.wrapped.fileno())
                path_info = await anyio.to_thread.run_sync(os.stat, self.path)
            except OSError:
                return await JSONResponse({'detail': 'ARTIFACT_CHANGED: 产物在下载打开时变化'}, status_code=409)(scope, receive, send)
            if file_identity(info) != self.identity or file_identity(path_info) != self.path_identity:
                return await JSONResponse({'detail': 'ARTIFACT_CHANGED: 产物在下载打开时变化'}, status_code=409)(scope, receive, send)
            self.set_stat_headers(info)
            headers = Headers(scope=scope)
            ranges = []
            if headers.get('range') and (not headers.get('if-range') or self._should_use_range(headers['if-range'])):
                try:
                    ranges = self._parse_range_header(headers['range'], info.st_size)
                except MalformedRangeHeader as error:
                    return await PlainTextResponse(error.content, status_code=400)(scope, receive, send)
                except RangeNotSatisfiable:
                    return await PlainTextResponse(status_code=416, headers={'Content-Range': f'bytes */{info.st_size}'})(scope, receive, send)
            output = MutableHeaders(raw=list(self.raw_headers))
            boundary, header_for = None, None
            if len(ranges) == 1:
                start, end = ranges[0]
                output['content-range'] = f'bytes {start}-{end-1}/{info.st_size}'
                output['content-length'] = str(end-start)
            elif ranges:
                boundary = token_hex(13)
                length, header_for = self.generate_multipart(ranges, boundary, info.st_size, self.headers['content-type'])
                output['content-type'] = f'multipart/byteranges; boundary={boundary}'
                output['content-length'] = str(length)
            await send({'type': 'http.response.start', 'status': 206 if ranges else self.status_code, 'headers': output.raw})
            if scope['method'].upper() != 'HEAD':
                for start, end in ranges or [(0, info.st_size)]:
                    if header_for:
                        await send({'type': 'http.response.body', 'body': header_for(start, end), 'more_body': True})
                    await file.seek(start)
                    while start < end:
                        chunk = await file.read(min(self.chunk_size, end-start))
                        # Concurrent writes cannot send a newly read chunk under
                        # the old proof. Rename races remain pinned to this fd.
                        current = await anyio.to_thread.run_sync(os.fstat, file.wrapped.fileno())
                        if not chunk or file_identity(current) != self.identity:
                            raise ArtifactIdentityError('ARTIFACT_CHANGED: 产物在下载期间变化')
                        start += len(chunk)
                        await send({'type': 'http.response.body', 'body': chunk, 'more_body': True})
                    if boundary:
                        await send({'type': 'http.response.body', 'body': b'\r\n', 'more_body': True})
                if boundary:
                    await send({'type': 'http.response.body', 'body': f'--{boundary}--'.encode('latin-1'), 'more_body': True})
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        if self.background:
            await self.background()
