const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
let selected = '', historyEvents = [];

async function api(path, data) {
    const response = await fetch(path, {
        method: 'POST',
        headers: {'X-Token': token, 'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    return result;
}

function notice(error) {
    $('notice').textContent = error.message || String(error);
}

$('login').onsubmit = async event => {
    event.preventDefault();
    try {
        await api('/api/login', {
            username: $('username').value, password: $('password').value,
            host: $('host').value, port: $('port').value
        });
        $('password').value = '';
        historyEvents = [];
        selected = '';
        $('channel').textContent = 'Global chat';
        render();
        $('notice').textContent = 'Connected';
    } catch (error) { notice(error); }
};
$('logout').onclick = () => api('/api/logout', {}).catch(notice);
$('compose').onsubmit = async event => {
    event.preventDefault();
    try {
        await api('/api/message', {text: $('text').value, recipient: selected});
        $('text').value = '';
    } catch (error) { notice(error); }
};
$('recipient').onchange = () => {
    selected = $('recipient').value;
    $('channel').textContent = selected ? `Chat with ${selected}` : 'Global chat';
    render();
};

function belongsToConversation(event, conversation) {
    if (event.type === 'GLOBAL_MESSAGE') return conversation === '';
    if (!['PRIVATE_MESSAGE', 'FILE_OFFER', 'FILE_RESULT', 'PROGRESS', 'ERROR'].includes(event.type)) {
        return false;
    }
    return Boolean(conversation) && event.conversation === conversation;
}

function appendEvents(events) {
    for (const event of events) {
        if (!['GLOBAL_MESSAGE', 'PRIVATE_MESSAGE', 'FILE_OFFER', 'FILE_RESULT', 'PROGRESS', 'ERROR'].includes(event.type)) {
            continue;
        }
        if (event.type === 'FILE_RESULT') {
            for (const item of historyEvents) {
                if (item.type === 'PROGRESS' && item.id === event.id && item.conversation === event.conversation) {
                    item.phase = event.success ? 'verified' : 'failed';
                    if (event.success) item.progress = 1;
                }
            }
        }
        if (event.type === 'PROGRESS') {
            const previous = historyEvents.findIndex(item =>
                item.type === 'PROGRESS' && item.id === event.id &&
                item.conversation === event.conversation
            );
            if (previous !== -1) {
                historyEvents[previous] = event;
                continue;
            }
        }
        historyEvents.push(event);
    }
    historyEvents = historyEvents.slice(-1000);
}

function render() {
    const box = $('messages');
    box.replaceChildren();
    for (const event of historyEvents) {
        if (!belongsToConversation(event, selected)) continue;
        const article = document.createElement('article');
        const author = document.createElement('b');
        author.textContent = event.sender || 'File transfer';
        article.append(author);
        const content = document.createElement('p');
        content.textContent = event.text || event.error || (
            event.type === 'FILE_RESULT'
                ? `${event.success ? 'Verified ✓' : 'Integrity check failed'} · ${event.name}`
                : event.type === 'PROGRESS'
                    ? `${event.name} · ${Math.round(event.progress * 100)}%${event.phase === 'received' && event.progress === 1 ? ' received · awaiting verification' : event.phase === 'verified' ? ' · verified' : ''}`
                    : `${event.type} · ${event.name || ''}`
        );
        article.append(content);
        if (event.type === 'PROGRESS') {
            const progress = document.createElement('progress');
            progress.max = 1;
            progress.value = event.progress;
            article.append(progress);
        }
        box.append(article);
    }
    box.scrollTop = box.scrollHeight;
}

$('upload').onclick = async () => {
    try {
        const file = $('file').files[0];
        if (!selected || !file) throw Error('Select a person and a file first');
        const response = await fetch(
            `/api/file?name=${encodeURIComponent(file.name)}&recipient=${encodeURIComponent(selected)}`,
            {method: 'POST', headers: {'X-Token': token}, body: file}
        );
        const result = await response.json();
        if (!response.ok) throw Error(result.error);
        $('notice').textContent = 'File queued for encrypted UDP transfer';
    } catch (error) { notice(error); }
};

let polling = false;
setInterval(async () => {
    if (polling) return;
    polling = true;
    try {
        const response = await fetch('/api/events', {headers: {'X-Token': token}});
        if (!response.ok) {
            throw Error('Bridge authorization failed. Open the full URL printed in your terminal.');
        }
        const state = await response.json();
        $('status').textContent = state.connected ? '● Connected' : '○ Disconnected';
        $('count').textContent = `${state.users.length} online`;
        const picker = $('recipient');
        picker.replaceChildren(new Option('# Global chat', ''));
        for (const user of state.users) {
            if (user.username !== $('username').value) {
                picker.add(new Option(user.username, user.username));
            }
        }
        picker.value = selected;
        for (const event of state.events) {
            if (event.type === 'ERROR' && !event.conversation) notice(event.error);
        }
        appendEvents(state.events);
        if (state.events.length) render();
    } catch (error) { notice(error); }
    finally { polling = false; }
}, 500);
