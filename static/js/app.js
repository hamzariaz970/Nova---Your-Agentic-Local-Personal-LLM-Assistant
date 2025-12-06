// Core DOM references
const appShell = document.querySelector('.app-shell');

const messagesDiv = document.getElementById('messages');
const chatForm = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const chatStatus = document.getElementById('chat-status');
const convoMeta = document.getElementById('conversation-meta');
const emptyState = document.getElementById('empty-state');
const thinkingBox = document.getElementById('thinking-box');

const convoList = document.getElementById('conversation-list');
const newChatBtn = document.getElementById('new-chat-btn');
const sidebarToggleBtn = document.getElementById('sidebar-toggle');

// Overlay / pages
const pageOverlay = document.getElementById('page-overlay');
const pageOverlayTitle = document.getElementById('page-overlay-title');
const pageOverlayBack = document.getElementById('page-overlay-back');
const tasksPage = document.getElementById('tasks-page');
const notesPage = document.getElementById('notes-page');
const settingsPage = document.getElementById('settings-page');

const openTasksPageBtn = document.getElementById('open-tasks-page');
const openNotesPageBtn = document.getElementById('open-notes-page');
const openSettingsPageBtn = document.getElementById('open-settings-page');

// Tasks DOM
const tasksList = document.getElementById('tasks-list');
const taskCreateForm = document.getElementById('task-create-form');
const taskTitleInput = document.getElementById('task-title-input');
const taskDueInput = document.getElementById('task-due-input');
const refreshTasksBtn = document.getElementById('refresh-tasks-btn');

// Notes DOM
const notesList = document.getElementById('notes-list');
const noteCreateForm = document.getElementById('note-create-form');
const noteTitleInput = document.getElementById('note-title-input');
const noteContentInput = document.getElementById('note-content-input');

// RAG DOM
const ragPage = document.getElementById('rag-page');
const openRagPageBtn = document.getElementById('open-rag-page');

// Settings DOM
const settingsList = document.getElementById('settings-list');

// Toasts
const toastContainer = document.getElementById('toast-container');

// State
let activeConversationId = null;
const remindedTaskIds = new Set();

// --------------------------------------------------------
// Utility helpers
// --------------------------------------------------------

function hideOrShowEmptyState() {
  if (!emptyState) return;
  const hasMessages = messagesDiv && messagesDiv.children.length > 0;
  emptyState.style.display = hasMessages ? 'none' : 'flex';
}

function addMessage(role, content) {
  const div = document.createElement('div');
  div.classList.add('message', role);

  const roleSpan = document.createElement('div');
  roleSpan.classList.add('message-role');
  roleSpan.textContent = role;

  const contentDiv = document.createElement('div');
  contentDiv.textContent = content;

  div.appendChild(roleSpan);
  div.appendChild(contentDiv);
  messagesDiv.appendChild(div);
  messagesDiv.scrollTop = messagesDiv.scrollHeight;

  hideOrShowEmptyState();
}

function updateConversationMeta(title, id) {
  if (title && title.trim()) {
    convoMeta.textContent = title.trim();
  } else if (id) {
    convoMeta.textContent = 'Conversation: ' + id.slice(0, 8);
  } else {
    convoMeta.textContent = 'Conversation';
  }
}

function escapeHtml(str) {
  return (str || '').replace(/[&<>"']/g, (ch) => {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return map[ch] || ch;
  });
}

function formatDateShort(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Toasts -------------------------------------------------

function showToast(text) {
  if (!toastContainer) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <div class="toast-indicator"></div>
    <div class="toast-body">${escapeHtml(text)}</div>
    <button class="toast-close" aria-label="Close">×</button>
  `;
  const closeBtn = toast.querySelector('.toast-close');
  closeBtn.addEventListener('click', () => {
    if (toast.parentElement === toastContainer) {
      toastContainer.removeChild(toast);
    }
  });
  toastContainer.appendChild(toast);

  setTimeout(() => {
    if (toast.parentElement === toastContainer) {
      toastContainer.removeChild(toast);
    }
  }, 15000);
}

// --------------------------------------------------------
// Conversations / history
// --------------------------------------------------------

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    if (!res.ok) {
      console.warn('history error', res.status);
      return;
    }
    const data = await res.json(); // {conversation_id, title, messages}
    messagesDiv.innerHTML = '';
    (data.messages || []).forEach((m) => {
      addMessage(m.role || 'assistant', m.content || '');
    });

    activeConversationId = data.conversation_id || null;
    updateConversationMeta(data.title, activeConversationId);
    hideOrShowEmptyState();
    await loadConversations();
  } catch (err) {
    console.error('loadHistory failed', err);
  }
}
function renderConversationList(conversations) {
  if (!convoList) return;

  convoList.innerHTML = '';
  if (!conversations.length) {
    convoList.innerHTML = '<span class="muted small">No conversations yet.</span>';
    return;
  }

  conversations.forEach((c) => {
    const btn = document.createElement('button');
    btn.classList.add('conversation-item');
    if (c.id === activeConversationId) {
      btn.classList.add('active');
    }

    const title = (c.title && c.title.trim()) ? c.title : 'Untitled chat';
    const created = c.created_at ? c.created_at.split('T')[0] : '';

    // NOTE: vertical ellipsis ⋮ so it's clearly 3 dots in a column
    btn.innerHTML = `
      <div class="conversation-item-row">
        <div class="conversation-text">
          <div class="conversation-title">${escapeHtml(title)}</div>
          <div class="conversation-meta muted small">${escapeHtml(created)}</div>
        </div>
        <div
          class="conversation-menu-btn"
          aria-label="Conversation options"
          role="button"
          tabindex="0"
        >⋮</div>
      </div>
    `;

    // Clicking the main button opens the conversation
    btn.addEventListener('click', () => {
      if (c.id === activeConversationId) return;
      loadConversation(c.id);
    });

    // 3-dots menu: delete chat
    const menuBtn = btn.querySelector('.conversation-menu-btn');
    if (menuBtn) {
      menuBtn.addEventListener('click', (ev) => {
        // Prevent the parent button click (which opens the chat)
        ev.stopPropagation();
        deleteConversation(c.id, title);
      });

      // keyboard support
      menuBtn.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          menuBtn.click();
        }
      });
    }

    convoList.appendChild(btn);
  });
}


async function loadConversations() {
  try {
    const res = await fetch('/api/conversations');
    if (!res.ok) return;
    const data = await res.json();
    renderConversationList(data.conversations || []);
  } catch (err) {
    console.error('loadConversations failed', err);
  }
}

async function loadConversation(id) {
  try {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) {
      console.warn('get_conversation error', res.status);
      return;
    }
    const data = await res.json(); // {id, title, messages}
    activeConversationId = data.id;
    messagesDiv.innerHTML = '';
    (data.messages || []).forEach((m) => {
      addMessage(m.role || 'assistant', m.content || '');
    });
    updateConversationMeta(data.title, data.id);
    hideOrShowEmptyState();
    await loadConversations();
  } catch (err) {
    console.error('loadConversation failed', err);
  }
}


function showThinking(text) {
  if (!thinkingBox) return;
  thinkingBox.innerHTML = `
    <span class="thinking-dot"></span>
    <span>${text}</span>
  `;
  thinkingBox.style.display = 'flex';
}

function hideThinking() {
  if (!thinkingBox) return;
  thinkingBox.style.display = 'none';
}

// --------------------------------------------------------
// Tasks
// --------------------------------------------------------

async function loadTasks() {
  if (!tasksList) return;
  try {
    const res = await fetch('/api/tasks?status=all');
    if (!res.ok) return;
    const data = await res.json();
    const tasks = data.tasks || [];
    renderTasksList(tasks);
  } catch (err) {
    console.error('loadTasks failed', err);
  }
}

function renderTasksList(tasks) {
  if (!tasksList) return;

  if (!tasks.length) {
    tasksList.innerHTML =
      '<span class="muted small">No tasks yet. Add one on the right or let the assistant create them from conversations.</span>';
    return;
  }

  const wrapper = document.createElement('div');
  wrapper.classList.add('tasks-list-inner');

  tasks.forEach((task) => {
    const card = document.createElement('div');
    card.classList.add('task-card');
    if (task.completed) card.classList.add('completed');

    const title = task.title || '(untitled task)';
    const createdStr = formatDateShort(task.created_at);
    const dueStr = formatDateShort(task.due_date);

    const tags = task.tags || [];

    card.innerHTML = `
      <div class="task-card-header">
        <div class="task-title">${escapeHtml(title)}</div>
        <span class="task-status muted small">${task.completed ? 'Completed' : 'Open'}</span>
      </div>
      <div class="task-meta">
        ${createdStr ? `<span>Created ${escapeHtml(createdStr)}</span>` : ''}
        ${dueStr ? `<span>Due ${escapeHtml(dueStr)}</span>` : ''}
      </div>
      <div class="task-tags">
        ${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
      </div>
      <div class="task-actions">
        <button class="task-btn complete">${task.completed ? 'Mark open' : 'Complete'}</button>
        <button class="task-btn edit">Edit</button>
        <button class="task-btn delete">Delete</button>
      </div>
    `;

    const completeBtn = card.querySelector('.task-btn.complete');
    const editBtn = card.querySelector('.task-btn.edit');
    const deleteBtn = card.querySelector('.task-btn.delete');

    completeBtn.addEventListener('click', async () => {
      await updateTask(task.id, { completed: !task.completed });
      await loadTasks();
    });

    editBtn.addEventListener('click', async () => {
      const newTitle = window.prompt('Edit task title:', task.title || '');
      if (newTitle === null) return;

      let newDueISO = task.due_date || null;
      const currentDue = task.due_date
        ? new Date(task.due_date).toISOString().slice(0, 16)
        : '';
      const newDueRaw = window.prompt(
        'Edit due date/time (YYYY-MM-DDTHH:MM or leave blank):',
        currentDue
      );
      if (newDueRaw !== null && newDueRaw.trim() !== '') {
        const d = new Date(newDueRaw);
        if (!Number.isNaN(d.getTime())) {
          newDueISO = d.toISOString();
        }
      } else if (newDueRaw !== null) {
        newDueISO = null;
      }

      await updateTask(task.id, {
        title: newTitle,
        due_date: newDueISO,
      });
      await loadTasks();
    });

    deleteBtn.addEventListener('click', async () => {
      if (!window.confirm('Delete this task?')) return;
      await deleteTask(task.id);
      await loadTasks();
    });

    wrapper.appendChild(card);
  });

  tasksList.innerHTML = '';
  tasksList.appendChild(wrapper);
}

async function createTask(task) {
  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(task),
    });
    if (!res.ok) {
      console.warn('createTask error', res.status);
    }
  } catch (err) {
    console.error('createTask failed', err);
  }
}

async function updateTask(taskId, patch) {
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) {
      console.warn('updateTask error', res.status);
    }
  } catch (err) {
    console.error('updateTask failed', err);
  }
}

async function deleteTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      console.warn('deleteTask error', res.status);
    }
  } catch (err) {
    console.error('deleteTask failed', err);
  }
}

// --------------------------------------------------------
// Notes
// --------------------------------------------------------

async function loadNotes() {
  if (!notesList) return;
  try {
    const res = await fetch('/api/notes?limit=200');
    if (!res.ok) return;
    const data = await res.json();
    const notes = data.notes || data || [];
    if (!notes.length) {
      notesList.innerHTML = '<span class="muted small">No notes yet.</span>';
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.classList.add('notes-list-inner');
    notes.forEach((n) => {
      const item = document.createElement('div');
      item.classList.add('note-item');
      const title = n.title || 'Untitled';
      const created = n.created_at ? n.created_at.split('T')[0] : '';
      item.innerHTML = `
        <div class="note-item-title">${escapeHtml(title)}</div>
        <div class="note-item-meta muted small">${escapeHtml(created)}</div>
      `;
      wrapper.appendChild(item);
    });
    notesList.innerHTML = '';
    notesList.appendChild(wrapper);
  } catch (err) {
    console.error('loadNotes failed', err);
  }
}

// --------------------------------------------------------
// Settings
// --------------------------------------------------------

async function loadSettings() {
  if (!settingsList) return;
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const data = await res.json();
    const settings = data.settings || {};
    settingsList.innerHTML = '';

    const entries = [
      ['use_web_search', 'Web search / http_get'],
      ['use_gmail', 'Gmail'],
      ['use_calendar', 'Calendar'],
      ['use_shell', 'Shell commands'],
    ];

    entries.forEach(([key, label]) => {
      const row = document.createElement('div');
      row.classList.add('setting-toggle');

      const span = document.createElement('span');
      span.textContent = label;

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = !!settings[key];
      checkbox.addEventListener('change', () => {
        updateSettings({ [key]: checkbox.checked });
      });

      row.appendChild(span);
      row.appendChild(checkbox);
      settingsList.appendChild(row);
    });
  } catch (err) {
    console.error('loadSettings failed', err);
  }
}

async function updateSettings(patch) {
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
  } catch (err) {
    console.error('updateSettings failed', err);
  }
}

// --------------------------------------------------------
// Chat sending / loading indicator
// --------------------------------------------------------

function setLoading(isLoading) {
  if (isLoading) {
    chatStatus.innerHTML = `
      <span class="spinner" aria-hidden="true"></span>
      <span>Thinking...</span>
    `;
    sendBtn.disabled = true;
    userInput.disabled = true;

    // new: high-level status
    showThinking('Understanding your request…');
  } else {
    chatStatus.textContent = '';
    sendBtn.disabled = false;
    userInput.disabled = false;
    userInput.focus();
    hideThinking();
  }
}

async function sendMessage(message) {
  setLoading(true);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: activeConversationId }),
    });
    if (!res.ok) {
      addMessage('system', 'Error from backend: ' + res.status);
      return;
    }
    const data = await res.json(); // {reply, conversation_id, conversation_title, messages}
    addMessage('assistant', data.reply || '');
    activeConversationId = data.conversation_id || activeConversationId;
    updateConversationMeta(data.conversation_title, activeConversationId);

    // Keep tasks/notes/settings in sync with LLM-created artifacts
    loadTasks();
    loadNotes();
    loadSettings();
  } catch (err) {
    console.error('sendMessage failed', err);
    addMessage('system', 'Request failed. Check console.');
  } finally {
    setLoading(false);
  }
}

// --------------------------------------------------------
// Reminder system (poll open tasks and ask LLM for text)
// --------------------------------------------------------

async function fetchReminderText(task) {
  try {
    const res = await fetch('/api/reminder_text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_title: task.title || '',
        due_date: task.due_date || null,
      }),
    });
    if (!res.ok) {
      console.warn('reminder_text error', res.status);
      return null;
    }
    const data = await res.json();
    return data.text || null;
  } catch (err) {
    console.error('fetchReminderText failed', err);
    return null;
  }
}

async function checkTaskReminders() {
  try {
    const res = await fetch('/api/tasks?status=open');
    if (!res.ok) return;
    const data = await res.json();
    const tasks = data.tasks || [];
    const now = new Date();

    for (const t of tasks) {
      if (!t.id || !t.due_date) continue;
      if (remindedTaskIds.has(t.id)) continue;

      const due = new Date(t.due_date);
      if (Number.isNaN(due.getTime())) continue;

      if (now >= due) {
        remindedTaskIds.add(t.id);
        const reminderText =
          (await fetchReminderText(t)) || `Reminder: ${t.title || 'Task is due'}`;
        showToast(reminderText);
      }
    }
  } catch (err) {
    console.error('checkTaskReminders failed', err);
  }
}

async function deleteConversation(conversationId, title) {
  if (!conversationId) return;

  const label = title && title.trim() ? title.trim() : 'Untitled chat';
  const confirmed = window.confirm(
    `Delete conversation "${label}"?\n\nThis cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      console.warn('deleteConversation error', res.status);
      return;
    }

    // After deletion, backend guarantees an active conversation exists.
    await loadConversations();
    await loadHistory();
  } catch (err) {
    console.error('deleteConversation failed', err);
  }
}

async function fetchRagFiles() {
  const res = await fetch("/api/rag/files");
  if (!res.ok) return;
  const data = await res.json();
  renderRagFiles(data.files || []);
}

function renderRagFiles(files) {
  const list = document.getElementById("rag-files-list");
  if (!list) return;

  list.innerHTML = "";

  if (!files.length) {
    const li = document.createElement("li");
    li.textContent = "No files indexed yet.";
    list.appendChild(li);
    return;
  }

  files.forEach((file) => {
    const li = document.createElement("li");
    li.className = "rag-file-item";

    const span = document.createElement("span");
    span.textContent = `${file.name} (${file.num_chunks} chunks)`;

    const btn = document.createElement("button");
    btn.className = "rag-delete-btn";
    btn.textContent = "Delete";
    btn.addEventListener("click", async () => {
      if (!confirm(`Delete RAG file: ${file.name}?`)) return;
      const res = await fetch(`/api/rag/files/${file.id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        const data = await res.json();
        renderRagFiles(data.files || []);
      }
    });

    li.appendChild(span);
    li.appendChild(btn);
    list.appendChild(li);
  });
}

function initRagUpload() {
  const form = document.getElementById("rag-upload-form");
  const input = document.getElementById("rag-file-input");
  const statusEl = document.getElementById("rag-upload-status");

  if (!form || !input) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!input.files.length) {
      if (statusEl) statusEl.textContent = "Please select at least one file.";
      return;
    }

    const formData = new FormData();
    for (const f of input.files) {
      formData.append("files", f);
    }

    if (statusEl) statusEl.textContent = "Uploading and indexing...";

    const res = await fetch("/api/rag/upload", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      if (statusEl) statusEl.textContent = "Upload failed.";
      return;
    }

    const data = await res.json();
    if (statusEl) statusEl.textContent = "Upload complete.";
    input.value = "";
    renderRagFiles(data.files || []);
  });
}

function closeOverlay() {
  if (!pageOverlay) return;

  // Hide the overlay itself
  pageOverlay.classList.add('hidden');

  // Also hide any visible page sections, just to be safe
  if (tasksPage) tasksPage.classList.add('hidden');
  if (notesPage) notesPage.classList.add('hidden');
  if (settingsPage) settingsPage.classList.add('hidden');
  if (ragPage) ragPage.classList.add('hidden');
}



// --------------------------------------------------------
// Overlay navigation
// --------------------------------------------------------
function openOverlay(page) {
  if (!pageOverlay) return;
  pageOverlay.classList.remove('hidden');

  // Hide all sections first
  if (tasksPage) tasksPage.classList.add('hidden');
  if (notesPage) notesPage.classList.add('hidden');
  if (settingsPage) settingsPage.classList.add('hidden');
  if (ragPage) ragPage.classList.add('hidden');

  if (page === 'tasks') {
    pageOverlayTitle.textContent = 'Tasks';
    if (tasksPage) tasksPage.classList.remove('hidden');
    loadTasks();
  } else if (page === 'notes') {
    pageOverlayTitle.textContent = 'Notes';
    if (notesPage) notesPage.classList.remove('hidden');
    loadNotes();
  } else if (page === 'settings') {
    pageOverlayTitle.textContent = 'Settings';
    if (settingsPage) settingsPage.classList.remove('hidden');
    loadSettings();
  } else if (page === 'rag') {
    pageOverlayTitle.textContent = 'Documents';
    if (ragPage) ragPage.classList.remove('hidden');
    // refresh list when opening
    fetchRagFiles();
  }
}



// --------------------------------------------------------
// Event listeners
// --------------------------------------------------------

// Chat form
chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = userInput.value.trim();
  if (!text) return;
  addMessage('user', text);
  userInput.value = '';
  sendMessage(text);
});

// New chat button
if (newChatBtn) {
  newChatBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        console.warn('create_conversation error', res.status);
        return;
      }
      const data = await res.json(); // {id, title}
      activeConversationId = data.id;
      messagesDiv.innerHTML = '';
      updateConversationMeta(data.title, data.id);
      hideOrShowEmptyState();
      await loadConversations();
    } catch (err) {
      console.error('new chat failed', err);
    }
  });
}

// Sidebar toggle
if (sidebarToggleBtn && appShell) {
  sidebarToggleBtn.addEventListener('click', () => {
    appShell.classList.toggle('sidebars-hidden');
  });
}

// Empty-state suggestion chips
if (emptyState) {
  emptyState.addEventListener('click', (e) => {
    const target = e.target;
    if (target.classList.contains('chip')) {
      userInput.value = target.textContent;
      userInput.focus();
    }
  });
}
function renderConversationList(conversations) {
  if (!convoList) return;

  convoList.innerHTML = '';
  if (!conversations.length) {
    convoList.innerHTML = '<span class="muted small">No conversations yet.</span>';
    return;
  }

  conversations.forEach((c) => {
    const btn = document.createElement('button');
    btn.classList.add('conversation-item');
    if (c.id === activeConversationId) {
      btn.classList.add('active');
    }

    const title = (c.title && c.title.trim()) ? c.title : 'Untitled chat';
    const created = c.created_at ? c.created_at.split('T')[0] : '';

    btn.innerHTML = `
      <div class="conversation-item-row">
        <div class="conversation-text">
          <div class="conversation-title">${escapeHtml(title)}</div>
          <div class="conversation-meta muted small">${escapeHtml(created)}</div>
        </div>
        <div
          class="conversation-menu-btn"
          aria-label="Conversation options"
          role="button"
          tabindex="0"
        >⋯</div>
      </div>
    `;

    // Clicking the main row opens the conversation
    btn.addEventListener('click', () => {
      if (c.id === activeConversationId) return;
      loadConversation(c.id);
    });

    // 3-dots menu: delete chat
    const menuBtn = btn.querySelector('.conversation-menu-btn');
    if (menuBtn) {
      menuBtn.addEventListener('click', (ev) => {
        // Prevent opening the conversation when clicking the dots
        ev.stopPropagation();
        deleteConversation(c.id, title);
      });

      // Keyboard accessibility
      menuBtn.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          menuBtn.click();
        }
      });
    }

    convoList.appendChild(btn);
  });
}




// Tasks overlay open
if (openTasksPageBtn) {
  openTasksPageBtn.addEventListener('click', () => openOverlay('tasks'));
}
if (openNotesPageBtn) {
  openNotesPageBtn.addEventListener('click', () => openOverlay('notes'));
}

if (openRagPageBtn) {
  openRagPageBtn.addEventListener('click', () => openOverlay('rag'));
}

if (openSettingsPageBtn) {
  openSettingsPageBtn.addEventListener('click', () => openOverlay('settings'));
}

// Overlay back button
if (pageOverlayBack) {
  pageOverlayBack.addEventListener('click', () => closeOverlay());
}

// Task create form
if (taskCreateForm) {
  taskCreateForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = taskTitleInput.value.trim();
    if (!title) return;

    const dueRaw = taskDueInput.value;
    let dueISO = null;
    if (dueRaw) {
      const d = new Date(dueRaw);
      if (!Number.isNaN(d.getTime())) {
        dueISO = d.toISOString();
      }
    }

    await createTask({ title, due_date: dueISO });
    taskTitleInput.value = '';
    taskDueInput.value = '';
    await loadTasks();
  });
}

// Refresh tasks
if (refreshTasksBtn) {
  refreshTasksBtn.addEventListener('click', () => loadTasks());
}

// Note create form
if (noteCreateForm) {
  noteCreateForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const content = noteContentInput.value.trim();
    if (!content) return;
    const title = noteTitleInput.value.trim() || null;

    try {
      await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          content,
          tags: [],
        }),
      });
      noteTitleInput.value = '';
      noteContentInput.value = '';
      await loadNotes();
    } catch (err) {
      console.error('create note failed', err);
    }
  });
}

// --------------------------------------------------------
// Initial load
// --------------------------------------------------------

window.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    loadTasks();
    loadNotes();
    loadSettings();

    initRagUpload();
    fetchRagFiles();

    // Periodic reminder check (every 60 seconds)
    setInterval(checkTaskReminders, 60 * 1000);

});
