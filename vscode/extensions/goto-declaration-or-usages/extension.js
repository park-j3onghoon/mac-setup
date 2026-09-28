'use strict';

const vscode = require('vscode');
const { createNavigator } = require('./navigator');

const LIBRARY_PATH = /\/(site-packages|dist-packages|node_modules|\.venv|venv)\//;

function activate(context) {
  const navigator = createNavigator({
    definitions: (uri, position) => execute('vscode.executeDefinitionProvider', uri, toPosition(position)),
    references: (uri, position) => execute('vscode.executeReferenceProvider', uri, toPosition(position)),
    documentSymbols: (uri) => execute('vscode.executeDocumentSymbolProvider', uri),
    documentText: async (uri) => (await vscode.workspace.openTextDocument(uri)).getText(),
    isClass: (symbol) => symbol.kind === vscode.SymbolKind.Class,
    isProjectFile: (uri) => Boolean(vscode.workspace.getWorkspaceFolder(uri)) && !LIBRARY_PATH.test(uri.path),
  });
  context.subscriptions.push(
    vscode.commands.registerCommand('gotoDeclarationOrUsages.run', () => run(navigator)),
  );
}

async function run(navigator) {
  const editor = vscode.window.activeTextEditor;
  const wordRange = editor && editor.document.getWordRangeAtPosition(editor.selection.active);
  if (!wordRange) {
    return vscode.commands.executeCommand('editor.action.revealDefinition');
  }
  const { document } = editor;
  const position = editor.selection.active;
  const word = document.getText(wordRange);
  const target = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: `Go to Declaration or Usages: ${word}` },
    () => navigator.resolve(document.uri, position, document.languageId),
  );
  if (target.kind === 'definition') {
    return vscode.commands.executeCommand('editor.action.revealDefinition');
  }
  // 0개면 커서 위 메시지, 1개면 바로 점프, 여러 개면 multipleReferences 설정(peek)대로 연다
  const multiple = vscode.workspace.getConfiguration('editor.gotoLocation', document).get('multipleReferences');
  const message = target.hasDefinition ? `No usages found for '${word}'` : `No definition or usages found for '${word}'`;
  return vscode.commands.executeCommand(
    'editor.action.goToLocations', document.uri, position, target.locations, multiple, message,
  );
}

async function execute(command, ...args) {
  return (await vscode.commands.executeCommand(command, ...args)) || [];
}

function toPosition(position) {
  return new vscode.Position(position.line, position.character);
}

module.exports = { activate };
