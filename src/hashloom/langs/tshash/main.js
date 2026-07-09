// Command tshash prints the sha256 of a TypeScript definition's normalised AST.
//
// Usage: node main.js <file.ts> <qualname> <projectRoot>
//
// This is the TypeScript analogue of hashloom's gohash (Go) and ast.dump (Python).
// TypeScript has no built-in AST serializer, so we hand-write a canonical walk
// over the Compiler API's AST: emit each node's SyntaxKind name plus the text of
// identifiers/literals, recurse into children in source order, and DROP what is
// not behaviour -- source positions, comments, JSDoc, and the export/default/
// declare modifiers. So formatting, comment, doc-comment, and export-visibility
// edits never change the hash, but a signature or body change does.
//
// `typescript` itself is resolved from the TARGET project's node_modules: the
// project's own compiler version is part of what we hash, mirroring how the Go
// adapter runs the target's own toolchain (GOTOOLCHAIN=local) and how hashloom
// verifies Python against the target's own venv.
//
// One line on stdout, exit 0 always (so a thrown error never collapses to a
// nonzero process exit the adapter would misread):
//
//   hash <64-hex>       a definition was found and hashed
//   not_found <msg>     the file, or the named definition, does not exist
//   syntax <msg>        the file is not valid TypeScript
//   notoolchain <msg>   `typescript` is not resolvable from the project

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function out(s) { process.stdout.write(s + '\n'); }
function oneline(s) { return String(s).replace(/\s+/g, ' ').trim(); }

function main() {
  const file = process.argv[2];
  const qual = process.argv[3];
  const projectRoot = process.argv[4] || path.dirname(file || '.');
  if (!file || !qual) { out('notoolchain usage: main.js <file> <qual> <root>'); return; }

  let ts;
  try {
    ts = require(require.resolve('typescript', { paths: [projectRoot] }));
  } catch (e) {
    out('notoolchain typescript not resolvable from ' + projectRoot + ' (npm i -D typescript)');
    return;
  }

  let source;
  try { source = fs.readFileSync(file, 'utf8'); }
  catch (e) { out('not_found file ' + file); return; }

  const sf = ts.createSourceFile(
    file, source, ts.ScriptTarget.Latest, /*setParentNodes*/ true, scriptKind(ts, file));

  // createSourceFile is error-tolerant (it returns a partial tree); the parse
  // errors live on the internal parseDiagnostics array. A non-empty array is the
  // TS equivalent of Go's parser.ParseFile returning an error.
  const diags = sf.parseDiagnostics || [];
  if (diags.length) {
    out('syntax ' + oneline(ts.flattenDiagnosticMessageText(diags[0].messageText, ' ')));
    return;
  }

  const node = findDef(ts, sf, qual);
  if (!node) { out('not_found def ' + qual); return; }

  const sum = crypto.createHash('sha256').update(serialize(ts, node)).digest('hex');
  out('hash ' + sum);
}

function scriptKind(ts, file) {
  return file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
}

// -- resolving the named definition ------------------------------------------

// findDef resolves either an implementation declaration (`foo`, `Foo`,
// `Foo.method`) or, failing that, a test call (`test('name', ...)` /
// `it('name', ...)`) whose name string is the qualname. The dual lookup lets
// test_source_hash fold a test's body into the verification key the same way the
// Go and Python adapters do.
function findDef(ts, sf, qual) {
  const decl = resolveChain(ts, sf.statements, qual.split('.'));
  if (decl) return decl;
  return findTestCall(ts, sf, qual);
}

function nameOf(ts, node) {
  const n = node.name;
  if (n && (ts.isIdentifier(n) || ts.isPrivateIdentifier(n) || ts.isStringLiteral(n))) return n.text;
  return undefined;
}

// childDecls returns the nested declaration scope to descend into for a dotted
// qualname: a class/interface's members, or a namespace body's statements.
function childDecls(ts, node) {
  if (ts.isClassDeclaration(node) || ts.isInterfaceDeclaration(node)) return node.members;
  if (ts.isModuleDeclaration(node) && node.body && node.body.statements) return node.body.statements;
  return null;
}

function resolveChain(ts, decls, segs) {
  if (!decls || !segs.length) return null;
  const head = segs[0];
  const rest = segs.slice(1);
  for (const d of decls) {
    // a `const foo = ...` is a VariableStatement wrapping declarations; descend
    // to the VariableDeclaration so the statement's `export` modifier is excluded
    const candidates = ts.isVariableStatement(d) ? d.declarationList.declarations : [d];
    for (const c of candidates) {
      if (nameOf(ts, c) !== head) continue;
      if (rest.length === 0) return c;
      const kids = childDecls(ts, c);
      const found = kids && resolveChain(ts, kids, rest);
      if (found) return found;
    }
  }
  return null;
}

function findTestCall(ts, sf, name) {
  let result = null;
  const visit = (node) => {
    if (result) return;
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      let id;
      if (ts.isIdentifier(callee)) id = callee.text;                                   // test(...)
      else if (ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.name)) id = callee.name.text; // test.only(...)
      if ((id === 'test' || id === 'it') && node.arguments.length >= 1) {
        const a0 = node.arguments[0];
        if ((ts.isStringLiteral(a0) || ts.isNoSubstitutionTemplateLiteral(a0)) && a0.text === name) {
          result = node;  // hash the whole call: its name + callback body
          return;
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return result;
}

// -- the canonical serialiser (the analogue of gohash's ast.Fprint+fieldFilter) -

function serialize(ts, node) {
  // export/default/declare are visibility plumbing, not behaviour: drop them so
  // `export function f` and a later un-exported `function f` hash the same.
  if (node.kind === ts.SyntaxKind.ExportKeyword ||
      node.kind === ts.SyntaxKind.DefaultKeyword ||
      node.kind === ts.SyntaxKind.DeclareKeyword) {
    return '';
  }
  const payload = leafText(ts, node);
  const parts = [];
  // forEachChild visits children in source order and, crucially, does NOT visit
  // comment/JSDoc trivia -- so those are dropped for free, like gohash's Doc/
  // Comment filter. We never read node positions, so formatting is invisible too.
  ts.forEachChild(node, (c) => {
    const s = serialize(ts, c);
    if (s) parts.push(s);
  });
  let s = ts.SyntaxKind[node.kind];
  if (payload !== undefined) s += '=' + payload;
  if (parts.length) s += '(' + parts.join(',') + ')';
  return s;
}

// leafText keeps the semantically-significant text of leaf nodes; structure is
// carried by the SyntaxKind name and children. Everything else returns undefined.
function leafText(ts, node) {
  switch (node.kind) {
    case ts.SyntaxKind.Identifier:
    case ts.SyntaxKind.PrivateIdentifier:
      return node.text;
    case ts.SyntaxKind.StringLiteral:
    case ts.SyntaxKind.NoSubstitutionTemplateLiteral:
      return JSON.stringify(node.text);  // normalise quoting style; text is unquoted
    case ts.SyntaxKind.NumericLiteral:
    case ts.SyntaxKind.BigIntLiteral:
    case ts.SyntaxKind.RegularExpressionLiteral:
      return node.text;
    default:
      return undefined;
  }
}

main();
