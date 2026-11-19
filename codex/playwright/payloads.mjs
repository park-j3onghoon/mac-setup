// Runs in the page before its value crosses CDP into the shared Node process.
export async function evaluateBounded({expression, limit = 8 * 1024 * 1024}, element) {
  const value = eval(`(${expression})`);
  let timer;
  let result;
  try {
    result = await Promise.race([
      typeof value === 'function' ? value(element) : value,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Evaluation exceeded 40 seconds; its page-side effects may still be pending.')), 40000); }),
    ]);
  } finally { clearTimeout(timer); }
  let characters = 0, nodes = 0;
  const ancestors = [];
  const text = JSON.stringify(result, function (key, value) {
    if (++nodes > 100000) throw new Error('Evaluation exceeds 100000 values; return a smaller result.');
    characters += key.length + (typeof value === 'string' ? value.length * 6 : 24);
    if (characters > limit) throw new Error('Evaluation exceeds the 8 MiB serialization budget; return a smaller result.');
    if (typeof value === 'bigint') return value.toString() + 'n';
    if (value && typeof value === 'object') {
      while (ancestors.length && ancestors.at(-1) !== this) ancestors.pop();
      if (ancestors.includes(value)) return '[Circular]';
      if (ancestors.length >= 30) throw new Error('Evaluation exceeds 30 levels; return a shallower result.');
      ancestors.push(value);
    }
    return value;
  }, 2);
  if (text && new TextEncoder().encode(text).length > limit)
    throw new Error('Evaluation exceeds 8 MiB; return a smaller result.');
  return text ?? String(result);
}
