document.addEventListener('DOMContentLoaded', function() {
    const loginForm = document.getElementById('login-form');
    const loginMessage = document.getElementById('login-message');

    // Se já existir um token, redireciona para o painel principal
    if (localStorage.getItem('access_token')) {
        window.location.href = '/static/index.html';
    }

    loginForm.addEventListener('submit', function(event) {
        event.preventDefault();
        loginMessage.style.display = 'none';

        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;

        // O FastAPI espera os dados de login como FormData
        const formData = new FormData();
        formData.append('username', username); // O 'username' aqui é a chave que o backend espera
        formData.append('password', password);

        fetch('/token', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                // Se a resposta não for 2xx, lança um erro para o .catch
                return response.json().then(err => { throw new Error(err.detail || 'Erro desconhecido'); });
            }
            return response.json();
        })
        .then(data => {
            if (data.access_token) {
                // Salva o token no armazenamento local
                localStorage.setItem('access_token', data.access_token);
                // Redireciona para a página principal
                window.location.href = '/static/index.html';
            }
        })
        .catch(error => {
            console.error('Erro de login:', error);
            loginMessage.textContent = 'Falha no login: ' + error.message;
            loginMessage.className = 'message error';
            loginMessage.style.display = 'block';
        });
    });
});