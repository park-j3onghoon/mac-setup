'use strict';

// PyCharm 의 Go to Declaration or Usages 판단을 VS Code API 와 무관하게 구현한다.
// host 는 언어 서버 질의를 감싼다: definitions·references(uri, position), documentSymbols·documentText(uri),
// isClass(symbol), isProjectFile(uri).

const MAX_ANCESTOR_CLASSES = 20;

function createNavigator(host) {
  return { resolve };

  async function resolve(uri, position, languageId) {
    const definitions = (await host.definitions(uri, position)).map(toLocation);
    // Kotlin(fwcd) 언어 서버는 선언 위에서 정의를 0개 돌려주므로 0개도 선언 위로 본다
    if (definitions.length > 0 && !definitions.some((location) => isAt(location, uri, position))) {
      return { kind: 'definition' };
    }
    const declarations = [...definitions];
    const references = [...(await host.references(uri, position))];
    if (languageId === 'python') {
      // 호출부가 추상 타입으로 부르면 언어 서버는 호출을 부모 메서드에 연결하므로 그쪽 사용처를 합친다
      for (const superMember of await findSuperMembersOrNone(uri, position)) {
        declarations.push(superMember);
        references.push(...(await host.references(superMember.uri, superMember.range.start)));
      }
    }
    const usages = references.filter(
      (location) => !isAt(location, uri, position)
        && !declarations.some((declaration) => sameStart(declaration, location)),
    );
    return { kind: 'usages', locations: uniqueByStart(usages), hasDefinition: definitions.length > 0 };
  }

  // 부모 탐색은 클래스 헤더를 텍스트로 읽는 추정이라, 실패해도 직접 사용처는 보여 준다
  async function findSuperMembersOrNone(uri, position) {
    try {
      return await findSuperMembers(uri, position);
    } catch (error) {
      console.warn('goto-declaration-or-usages: 부모 멤버 탐색 실패', error);
      return [];
    }
  }

  async function findSuperMembers(uri, position) {
    const path = symbolPathAt(await host.documentSymbols(uri), position);
    const member = path[path.length - 1];
    const owner = path[path.length - 2];
    if (!owner || !host.isClass(owner) || !contains(member.selectionRange, position)) {
      return [];
    }
    const superMembers = [];
    const visited = new Set();
    const queue = await baseClassesOf(uri, owner);
    while (queue.length > 0 && visited.size < MAX_ANCESTOR_CLASSES) {
      const base = queue.shift();
      const key = startKey(base.uri, base.symbol.selectionRange);
      if (visited.has(key)) {
        continue;
      }
      visited.add(key);
      const same = (base.symbol.children || []).find((child) => child.name === member.name && !host.isClass(child));
      if (same) {
        superMembers.push({ uri: base.uri, range: same.selectionRange });
      }
      queue.push(...(await baseClassesOf(base.uri, base.symbol)));
    }
    return superMembers;
  }

  async function baseClassesOf(uri, classSymbol) {
    const text = await host.documentText(uri);
    const starts = lineStarts(text);
    const bases = [];
    for (const offset of baseNameOffsets(text, offsetAt(starts, classSymbol.selectionRange.end))) {
      const definitions = (await host.definitions(uri, positionAt(starts, offset))).map(toLocation);
      // dict·Model 같은 라이브러리 부모까지 가면 워크스페이스의 모든 dict.get 호출이 섞이므로 프로젝트 소스만 본다
      for (const definition of definitions.filter((location) => host.isProjectFile(location.uri))) {
        const symbol = classSymbolAt(await host.documentSymbols(definition.uri), definition.range.start, host.isClass);
        if (symbol) {
          bases.push({ uri: definition.uri, symbol });
        }
      }
    }
    return bases;
  }
}

function toLocation(item) {
  return item.targetUri
    ? { uri: item.targetUri, range: item.targetSelectionRange || item.targetRange }
    : { uri: item.uri, range: item.range };
}

function isAt(location, uri, position) {
  return String(location.uri) === String(uri) && contains(location.range, position);
}

function sameStart(a, b) {
  return startKey(a.uri, a.range) === startKey(b.uri, b.range);
}

function uniqueByStart(locations) {
  const seen = new Set();
  return locations.filter((location) => {
    const key = startKey(location.uri, location.range);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function startKey(uri, range) {
  return `${uri}:${range.start.line}:${range.start.character}`;
}

function contains(range, position) {
  return Boolean(range) && !isBefore(position, range.start) && !isBefore(range.end, position);
}

function isBefore(a, b) {
  return a.line < b.line || (a.line === b.line && a.character < b.character);
}

function symbolPathAt(symbols, position) {
  const path = [];
  let level = symbols || [];
  for (;;) {
    const hit = level.find((symbol) => contains(symbol.range, position));
    if (!hit) {
      return path;
    }
    path.push(hit);
    level = hit.children || [];
  }
}

function classSymbolAt(symbols, position, isClass) {
  for (const symbol of symbols || []) {
    if (!contains(symbol.range, position)) {
      continue;
    }
    const inner = classSymbolAt(symbol.children, position, isClass);
    if (inner) {
      return inner;
    }
    if (isClass(symbol) && (contains(symbol.selectionRange, position) || symbol.range.start.line === position.line)) {
      return symbol;
    }
  }
  return undefined;
}

// `class Name[T](pkg.Base, Other[K, V], metaclass=M):` 에서 부모 이름 마지막 토막(Base, Other)의 오프셋
function baseNameOffsets(text, from) {
  let open = skipSpaces(text, from);
  if (text[open] === '[') {
    const typeParamsEnd = matchingClose(text, open);
    if (typeParamsEnd < 0) {
      return [];
    }
    open = skipSpaces(text, typeParamsEnd + 1);
  }
  if (text[open] !== '(') {
    return [];
  }
  const close = matchingClose(text, open);
  const offsets = [];
  let argumentStart = open + 1;
  let depth = 0;
  for (let i = argumentStart; i <= close; i++) {
    if ('([{'.includes(text[i])) {
      depth++;
    } else if (depth > 0 && ')]}'.includes(text[i])) {
      depth--;
    } else if (depth === 0 && (text[i] === ',' || i === close)) {
      const offset = baseNameOffset(text.slice(argumentStart, i));
      if (offset !== undefined) {
        offsets.push(argumentStart + offset);
      }
      argumentStart = i + 1;
    }
  }
  return offsets;
}

function baseNameOffset(argument) {
  const lead = /^(?:\s|#[^\n]*)*/.exec(argument)[0].length;
  const match = /^([A-Za-z_][\w.]*)\s*(?:\[|#|$)/.exec(argument.slice(lead));
  return match ? lead + match[1].lastIndexOf('.') + 1 : undefined;
}

function matchingClose(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if ('([{'.includes(text[i])) {
      depth++;
    } else if (')]}'.includes(text[i]) && --depth === 0) {
      return i;
    }
  }
  return -1;
}

function skipSpaces(text, index) {
  let i = index;
  while (i < text.length && /\s/.test(text[i])) {
    i++;
  }
  return i;
}

function lineStarts(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\n') {
      starts.push(i + 1);
    }
  }
  return starts;
}

function offsetAt(starts, position) {
  return starts[position.line] + position.character;
}

function positionAt(starts, offset) {
  let line = 0;
  while (line + 1 < starts.length && starts[line + 1] <= offset) {
    line++;
  }
  return { line, character: offset - starts[line] };
}

module.exports = { createNavigator, baseNameOffsets };
