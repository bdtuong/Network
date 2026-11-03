const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

class Element {
    constructor() { this.children = []; this.textContent = ''; this.value = ''; }
    append(child) { this.children.push(child); }
    replaceChildren(...children) { this.children = children; }
}

function frontend() {
    const elements = new Map();
    const context = vm.createContext({
        document: {
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, new Element());
                return elements.get(id);
            },
            createElement() { return new Element(); }
        },
        location: {hash: '#test', pathname: '/'},
        history: {replaceState() {}},
        setInterval() {}
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../network_app/web/app.js'), 'utf8'), context);
    return {context, elements};
}

const aliceFile = [
    {type: 'FILE_OFFER', id: 'alice-file', conversation: 'Alice', name: 'private.pdf'},
    {type: 'PROGRESS', id: 'alice-file', conversation: 'Alice', name: 'private.pdf', progress: .5},
    {type: 'FILE_RESULT', id: 'alice-file', conversation: 'Alice', name: 'private.pdf', success: true},
    {type: 'ERROR', id: 'alice-file', conversation: 'Alice', error: 'Transfer expired'}
];

function render(context, elements, events, conversation) {
    context.inputEvents = events;
    context.inputConversation = conversation;
    vm.runInContext('historyEvents = inputEvents; selected = inputConversation; render();', context);
    return elements.get('messages').children;
}

for (const conversation of ['', 'Charlie']) {
    test(`Alice's private file is hidden in ${conversation || 'Global chat'}`, () => {
        const {context, elements} = frontend();
        const cards = render(context, elements, aliceFile, conversation);
        assert.equal(cards.length, 0);
    });
}

test('file offer, progress, result and failure appear in the Alice conversation', () => {
    const {context, elements} = frontend();
    const cards = render(context, elements, aliceFile, 'Alice');
    assert.equal(cards.length, 4);
    assert.equal(cards[1].children[2].value, .5);
    assert.match(cards[2].children[1].textContent, /Verified/);
});

test('switching channels removes unrelated cards and restores the correct history', () => {
    const {context, elements} = frontend();
    const events = [
        ...aliceFile,
        {type: 'GLOBAL_MESSAGE', text: 'public'},
        {type: 'PRIVATE_MESSAGE', conversation: 'Alice', text: 'Alice private'},
        {type: 'PRIVATE_MESSAGE', conversation: 'Charlie', text: 'Charlie private'},
        {type: 'PROGRESS', conversation: 'Charlie', name: 'charlie.pdf', progress: .2}
    ];
    const global = render(context, elements, events, '');
    assert.equal(global.length, 1);
    assert.equal(global[0].children[1].textContent, 'public');
    const charlie = render(context, elements, events, 'Charlie');
    assert.equal(charlie.length, 2);
    assert.equal(charlie[0].children[1].textContent, 'Charlie private');
    assert.equal(render(context, elements, events, 'Alice').length, 5);
});

test('unscoped events and raw chunk records never appear as private chat cards', () => {
    const {context, elements} = frontend();
    const events = [
        {type: 'PROGRESS', name: 'unknown.pdf', progress: .5},
        {type: 'ERROR', error: 'Disconnected'},
        {type: 'FILE_CHUNK', conversation: 'Alice', data: 'binary'},
        {type: 'FILE_ACK', conversation: 'Alice'},
        {type: 'USER_LIST', users: []}
    ];
    assert.equal(render(context, elements, events, 'Alice').length, 0);
    assert.equal(render(context, elements, events, '').length, 0);
});


test('sender keeps hello after thousands of file ACKs and progress updates', () => {
    const {context, elements} = frontend();
    context.inputEvents = [{type: 'PRIVATE_MESSAGE', conversation: 'Bob', text: 'hello'}];
    vm.runInContext("selected = 'Bob'; appendEvents(inputEvents); render();", context);
    assert.equal(elements.get('messages').children[0].children[1].textContent, 'hello');
    for (let batch = 0; batch < 25; batch++) {
        context.inputEvents = Array.from({length: 100}, (_, index) => ({
            type: 'FILE_ACK', id: 'file', index: batch * 100 + index
        }));
        context.inputEvents.push(...Array.from({length: 50}, (_, index) => ({
            type: 'PROGRESS', id: 'file', conversation: 'Bob',
            name: 'large.pdf', progress: (batch * 50 + index + 1) / 1250
        })));
        vm.runInContext('appendEvents(inputEvents); render();', context);
    }
    context.inputEvents = [{type: 'FILE_RESULT', id: 'file', conversation: 'Bob',
                            name: 'large.pdf', success: true}];
    vm.runInContext('appendEvents(inputEvents); render();', context);
    const cards = elements.get('messages').children;
    assert.equal(cards.length, 3);
    assert.equal(cards[0].children[1].textContent, 'hello');
    assert.equal(cards[1].children[2].value, 1);
    assert.match(cards[2].children[1].textContent, /Verified/);
    vm.runInContext("selected = ''; render();", context);
    assert.equal(elements.get('messages').children.length, 0);
    vm.runInContext("selected = 'Bob'; render();", context);
    assert.equal(elements.get('messages').children[0].children[1].textContent, 'hello');
});
