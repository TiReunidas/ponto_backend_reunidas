// Esta função será executada assim que a página terminar de carregar
document.addEventListener('DOMContentLoaded', function() {
    // Encontra o elemento <ul> no nosso HTML
    const employeeList = document.getElementById('employee-list');

    // A função fetch faz a chamada de rede para a nossa API Python
    fetch('/employees')
        .then(response => response.json()) // Converte a resposta para JSON
        .then(data => {
            // Limpa a mensagem "Carregando..."
            employeeList.innerHTML = '';

            if (data.employees && data.employees.length > 0) {
                // Para cada funcionário na lista, cria um item <li> e o adiciona à tela
                data.employees.forEach(employeeId => {
                    const listItem = document.createElement('li');
                    listItem.textContent = `Matrícula: ${employeeId}`;
                    employeeList.appendChild(listItem);
                });
            } else {
                // Se a lista estiver vazia, mostra uma mensagem
                const listItem = document.createElement('li');
                listItem.textContent = 'Nenhum funcionário cadastrado.';
                employeeList.appendChild(listItem);
            }
        })
        .catch(error => {
            // Se ocorrer um erro na comunicação, mostra no console e na tela
            console.error('Erro ao buscar funcionários:', error);
            employeeList.innerHTML = '<li>Erro ao carregar a lista.</li>';
        });
});