"""Project counters from large JSONL records without retaining their message bodies."""
import json
import re

TOKEN = re.compile(rb'\s+|[{}\[\]:,"]|[^\s{}\[\]:,"]+')
STRING_DELIMITER = re.compile(rb'["\\]')


def tokens(stream, size):
    string = escape = False
    value = bytearray()
    while size:
        block = stream.read(min(size, 32768))
        if not block:
            raise ValueError('Incomplete usage record')
        size -= len(block)
        pos = 0
        while pos < len(block):
            if string:
                if escape:
                    piece = block[pos:pos + 1]
                    pos += 1
                    escape = False
                else:
                    mark = STRING_DELIMITER.search(block, pos)
                    stop = mark.end() if mark else len(block)
                    piece = block[pos:stop]
                    pos = stop
                    if mark:
                        escape = mark.group() == b'\\'
                        string = escape
                value.extend(piece[:max(0, 4096 - len(value))])
                if not string:
                    yield bytes(value) if len(value) < 4096 else b'""'
                    value.clear()
                continue
            match = TOKEN.match(block, pos)
            piece = match.group()
            pos = match.end()
            if piece[:1] not in b'{}[]:," \t\r\n':
                value.extend(piece[:max(0, 4096 - len(value))])
                continue
            if value:
                yield bytes(value)
                value.clear()
            if piece == b'"':
                string = True
                value.extend(piece)
            elif not piece.isspace():
                yield piece
    if string:
        raise ValueError('Incomplete string in usage record')
    if value:
        yield bytes(value)


def project(stream, size, fields):
    source = iter(tokens(stream, size))

    def read_object(wanted):
        result = {}
        token = next(source)
        while token != b'}':
            if not token.startswith(b'"') or next(source) != b':':
                raise ValueError('Invalid usage record')
            key = json.loads(token)
            value = next(source)
            if key in wanted and isinstance(wanted[key], dict) and value == b'{':
                result[key] = read_object(wanted[key])
            elif value in (b'{', b'['):
                depth = 1
                while depth:
                    item = next(source)
                    depth += (item in (b'{', b'[')) - (item in (b'}', b']'))
            elif key in wanted:
                result[key] = json.loads(value)
            token = next(source)
            if token == b',':
                token = next(source)
            elif token != b'}':
                raise ValueError('Invalid usage record')
        return result

    try:
        if next(source) != b'{':
            raise ValueError('Expected a usage object')
        result = read_object({'type': None, 'timestamp': None,
                              'message': {'model': None, 'id': None, 'usage': dict.fromkeys(fields)}})
        if next(source, None) is not None:
            raise ValueError('Trailing data in usage record')
        return result
    except StopIteration as error:
        raise ValueError('Incomplete usage record') from error
