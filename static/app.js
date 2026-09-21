const authSection = document.getElementById('auth-section');
const agentSection = document.getElementById('agent-section');
const registerForm = document.getElementById('register-form');
const loginForm = document.getElementById('login-form');
const statusMsg = document.getElementById('status-msg');
const userDisplay = document.getElementById('user-display');
const logoutBtn = document.getElementById('logout-btn');

const promptInput = document.getElementById('prompt-input');
const sendPromptBtn = document.getElementById('send-prompt-btn');
const agentOutput = document.getElementById('agent-output');

window.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('access_token');
    const username = localStorage.getItem('username');
    if (token && username) {
        showAgentView(username);
    }
});

// 1. REGISTER -> /register (JSON)
registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('reg-username').value.trim();
    const password = document.getElementById('reg-password').value.trim();

    try {
        const response = await fetch('/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Registration failed');

        showMessage('Registration successful! Please login.', 'success');
        registerForm.reset();
    } catch (err) {
        showMessage(err.message, 'error');
    }
});

// 2. OAUTH2 LOGIN -> /token (x-www-form-urlencoded)
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value.trim();

    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    try {
        const response = await fetch('/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Login failed');

        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        localStorage.setItem('username', data.username);
        
        loginForm.reset();
        hideMessage();
        showAgentView(data.username);
    } catch (err) {
        showMessage(err.message, 'error');
    }
});

// Helper: Refresh Access Token
async function refreshAccessToken() {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) return false;

    try {
        const response = await fetch('/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        });

        if (!response.ok) return false;

        const data = await response.json();
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        return true;
    } catch {
        return false;
    }
}

// Helper: Authenticated Fetch with Automatic Retry on Token Expiration
async function authenticatedFetch(url, options = {}) {
    let token = localStorage.getItem('access_token');
    options.headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`
    };

    let response = await fetch(url, options);

    if (response.status === 401) {
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            token = localStorage.getItem('access_token');
            options.headers['Authorization'] = `Bearer ${token}`;
            response = await fetch(url, options);
        } else {
            handleLogout();
            throw new Error('Session expired. Please log in again.');
        }
    }
    return response;
}

// 3. RUN LANGGRAPH AGENT -> /api/agent
sendPromptBtn.addEventListener('click', async () => {
    const prompt = promptInput.value.trim();
    if (!prompt) return alert('Please enter a prompt');

    agentOutput.textContent = 'LangGraph Agent processing...';

    try {
        const response = await authenticatedFetch('/api/agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Agent execution failed');

        agentOutput.textContent = data.reply;
    } catch (err) {
        agentOutput.textContent = `Error: ${err.message}`;
    }
});

// 4. LOGOUT
logoutBtn.addEventListener('click', handleLogout);

async function handleLogout() {
    const refreshToken = localStorage.getItem('refresh_token');
    if (refreshToken) {
        await fetch('/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken })
        }).catch(() => {});
    }

    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('username');
    agentSection.style.display = 'none';
    authSection.style.display = 'block';
    hideMessage();
}

function showAgentView(username) {
    authSection.style.display = 'none';
    agentSection.style.display = 'block';
    userDisplay.textContent = username;
}

function showMessage(text, type) {
    statusMsg.textContent = text;
    statusMsg.className = `message ${type}`;
    statusMsg.style.display = 'block';
}

function hideMessage() {
    statusMsg.style.display = 'none';
}
