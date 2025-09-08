document.addEventListener('DOMContentLoaded', function() {

    
    // --- VERIFICAÇÃO DE AUTENTICAÇÃO ---
    const token = localStorage.getItem('access_token');
    if (!token) {
        // Se não há token, redireciona para a página de login
        window.location.href = '/static/login.html';
        return; // Para a execução do script
    }



    // --- Referências aos Elementos do HTML ---
    const employeeList = document.getElementById('employee-list');
    const formCadastro = document.getElementById('employee-form');
    const statusMessage = document.getElementById('status-message');

    const detailsCard = document.getElementById('employee-details-section');
    const detailsEmployeeName = document.getElementById('details-employee-name');
    const punchTableBody = document.getElementById('punch-table-body');

    const formManualPunch = document.getElementById('form-manual-punch');
    const calculationForm = document.getElementById('calculation-form');
    const calculationResultDiv = document.getElementById('calculation-result');
    
    // Novos elementos para o fluxo de cálculo
    const fetchHoursBtn = document.getElementById('fetch-hours-btn');
    const confirmationArea = document.getElementById('confirmation-area');
    
    let currentEmployeeId = null;
    let currentEmployeeName = null;

    // =================================================================
    // 1. FUNÇÕES DE CARREGAMENTO (loadEmployees, loadPunches)
    // =================================================================
    function loadEmployees() {
        const token = localStorage.getItem('access_token'); // Pega o token salvo

        fetch('/employees', {
            headers: {
                'Authorization': `Bearer ${token}` // Adiciona o cabeçalho de autorização
            }
        })
        .then(response => {
            // É uma boa prática verificar se o token expirou
            if (response.status === 401) {
                // Se não autorizado, limpa o token e redireciona para o login
                localStorage.removeItem('access_token');
                window.location.href = '/static/login.html';
                return;
            }
            return response.json();
        })
        .then(data => {
            employeeList.innerHTML = '';
            if (data.employees && data.employees.length > 0) {
                data.employees.forEach(emp => {
                    const listItem = document.createElement('li');
                    listItem.textContent = `${emp.name} (Matrícula: ${emp.employee_id})`;
                    listItem.className = 'employee-item';
                    listItem.addEventListener('click', () => loadPunches(emp.employee_id, emp.name));
                    employeeList.appendChild(listItem);
                });
            } else {
                employeeList.innerHTML = '<li>Nenhum funcionário registado.</li>';
            }
        }).catch(error => {
            console.error('Erro ao procurar funcionários:', error);
            employeeList.innerHTML = '<li>Erro ao carregar a lista de funcionários.</li>';
        });
    }

    function loadPunches(employeeId, employeeName) {
        currentEmployeeId = employeeId;
        currentEmployeeName = employeeName;
        detailsEmployeeName.textContent = `${employeeName} (${employeeId})`;
        punchTableBody.innerHTML = '<tr><td colspan="5">A carregar histórico...</td></tr>';
        
        // Esconde e re-configura a secção de cálculo ao selecionar um novo funcionário
        detailsCard.style.display = 'block';
        confirmationArea.style.display = 'none';
        calculationResultDiv.innerHTML = '';
        document.getElementById('calculation-month').value = '';

        fetch(`/punches/${employeeId}`)
        .then(response => response.json())
        .then(data => {
            punchTableBody.innerHTML = '';
            if (data.punches && data.punches.length > 0) {
                data.punches.forEach(punch => {
                    const row = document.createElement('tr');
                    const timestamp = new Date(punch.timestamp).toLocaleString('pt-BR');
                    const verificationStatus = punch.verified ? '✅ Verificado' : '❌ Falha';
                    const photoLink = !punch.verified && punch.photo_path ? `<a href="/punch-photos/${punch.photo_path}" target="_blank">Ver Foto</a>` : 'N/A';
                    const actionsCell = `<td><button class="delete-btn" data-punch-id="${punch.id}">Apagar</button></td>`;
                    row.innerHTML = `<td>${timestamp}</td><td>${punch.type}</td><td class="${punch.verified ? 'verified' : 'unverified'}">${verificationStatus}</td><td>${photoLink}</td>${actionsCell}`;
                    punchTableBody.appendChild(row);
                });
            } else {
                punchTableBody.innerHTML = '<tr><td colspan="5">Nenhum ponto registado para este funcionário.</td></tr>';
            }
        }).catch(error => {
            console.error(`Erro ao procurar pontos para ${employeeId}:`, error);
            punchTableBody.innerHTML = '<tr><td colspan="5">Erro ao carregar o histórico.</td></tr>';
        });
    }

    // =================================================================
    // 2. LÓGICA DOS FORMULÁRIOS (Cadastro, Manual, Apagar)
    // =================================================================
    
    // --- Formulário de Cadastro de Funcionário ---
    formCadastro.addEventListener('submit', function(event) {
        event.preventDefault();
        statusMessage.textContent = 'A registar...';
        statusMessage.className = 'message';

        const formData = new FormData();
        formData.append('employee_name', document.getElementById('employee-name').value);
        formData.append('employee_id', document.getElementById('employee-id').value);
        formData.append('photo', document.getElementById('employee-photo').files[0]);

        fetch('/employees', {
            method: 'POST',
            body: formData 
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                statusMessage.textContent = data.message;
                statusMessage.className = 'message success';
                formCadastro.reset();
                loadEmployees(); // Recarrega a lista após o sucesso
            } else {
                statusMessage.textContent = 'Erro: ' + data.detail;
                statusMessage.className = 'message error';
            }
        })
        .catch(error => {
            console.error('Erro ao registar funcionário:', error);
            statusMessage.textContent = 'Erro de comunicação com o servidor.';
            statusMessage.className = 'message error';
        });
    });

    // --- Formulário de Batida Manual ---
    formManualPunch.addEventListener('submit', function(event) {
        event.preventDefault();
        const manualDatetime = document.getElementById('manual-datetime').value;
        const manualType = document.getElementById('manual-type').value;

        if (!manualDatetime || !currentEmployeeId) {
            alert('Por favor, preencha a data/hora e selecione um funcionário.');
            return;
        }

        // Converte a data local para timestamp Unix em milissegundos
        const timestamp = new Date(manualDatetime).getTime();

        const requestBody = {
            employee_id: currentEmployeeId,
            timestamp: timestamp,
            type: manualType
        };

        fetch('/punches/manual', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestBody)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(data.message);
                formManualPunch.reset();
                // Recarrega os pontos para vermos a nova batida
                loadPunches(currentEmployeeId, currentEmployeeName); 
            } else {
                alert('Erro ao adicionar ponto manual: ' + data.detail);
            }
        })
        .catch(error => {
            console.error('Erro na batida manual:', error);
            alert('Erro de comunicação ao tentar adicionar o ponto manual.');
        });
    });

    // --- Lógica para Apagar Ponto (usando delegação de evento) ---
    punchTableBody.addEventListener('click', function(event) {
        if (event.target && event.target.classList.contains('delete-btn')) {
            const punchId = event.target.getAttribute('data-punch-id');
            
            if (confirm(`Tem a certeza que quer apagar este registo de ponto (ID: ${punchId})?`)) {
                fetch(`/punches/${punchId}`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        alert(data.message);
                        // Recarrega os pontos para refletir a exclusão
                        loadPunches(currentEmployeeId, currentEmployeeName);
                    } else {
                        alert('Erro ao apagar o registo: ' + data.detail);
                    }
                })
                .catch(error => {
                    console.error('Erro ao apagar ponto:', error);
                    alert('Erro de comunicação com o servidor ao tentar apagar o registo.');
                });
            }
        }
    });
        

    // =================================================================
    // 3. LÓGICA DO CÁLCULO MENSAL (FLUXO "BUSCAR E CONFIRMAR")
    // =================================================================
    fetchHoursBtn.addEventListener('click', function() {
        const monthValue = document.getElementById('calculation-month').value;
        if (!monthValue || !currentEmployeeId) {
            alert('Selecione um funcionário e um mês primeiro.');
            return;
        }
        
        const [year, month] = monthValue.split('-').map(Number);
        
        confirmationArea.style.display = 'block';
        document.getElementById('main-system-hours-50').value = 'A procurar...';
        document.getElementById('main-system-hours-100').value = 'A procurar...';

        // Chama a API para buscar os dados do sistema principal
        fetch(`/main-system-hours?employee_id=${currentEmployeeId}&year=${year}&month=${month}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Preenche os campos com os valores retornados pela API
                document.getElementById('main-system-hours-50').value = data.main_system_hours_50.toFixed(2);
                document.getElementById('main-system-hours-100').value = data.main_system_hours_100.toFixed(2);
            } else {
                alert('Erro ao procurar dados do sistema principal.');
                document.getElementById('main-system-hours-50').value = '0.00';
                document.getElementById('main-system-hours-100').value = '0.00';
            }
        })
        .catch(error => {
            console.error("Erro ao buscar horas do sistema principal:", error);
            alert("Erro de comunicação ao buscar dados do sistema principal.");
            document.getElementById('main-system-hours-50').value = '0.00';
            document.getElementById('main-system-hours-100').value = '0.00';
        });
    });

     function logout() {
        localStorage.removeItem('access_token');
        window.location.href = '/static/login.html';
    }

    // Adicione um botão de logout no seu HTML (index.html) e associe a esta função
    // Ex: <button id="logout-btn">Sair</button>
    // const logoutBtn = document.getElementById('logout-btn');
    // if(logoutBtn) logoutBtn.addEventListener('click', logout);


    // --- ATUALIZE TODAS AS CHAMADAS fetch() ---
    // Crie um cabeçalho reutilizável com o token
    const authHeaders = {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json' // Para POST/PUT com JSON
    };

    // Exemplo de como modificar uma chamada fetch:
    function loadEmployees() {
        fetch('/employees', {
            headers: { 'Authorization': `Bearer ${token}` } // Adiciona o cabeçalho
        })
        .then(response => {
            if (response.status === 401) logout(); // Se não autorizado, faz logout
            return response.json();
        })
        .then(data => {
            // ... (resto da sua função loadEmployees)
        }).catch(error => {
            console.error('Erro ao procurar funcionários:', error);
        });
    }




    calculationForm.addEventListener('submit', function(event) {
        event.preventDefault();
        const monthValue = document.getElementById('calculation-month').value;
        // Lê os valores dos campos (que podem ter sido editados pelo RH)
        const mainSystemHours50 = parseFloat(document.getElementById('main-system-hours-50').value) || 0;
        const mainSystemHours100 = parseFloat(document.getElementById('main-system-hours-100').value) || 0;
        
        if (!monthValue) { alert('Por favor, selecione um mês e ano.'); return; }
        
        const [year, month] = monthValue.split('-').map(Number);
        
        calculationResultDiv.innerHTML = `<p class="loading">A calcular...</p>`;
        const requestBody = {
            employee_id: currentEmployeeId,
            year: year,
            month: month,
            main_system_hours_50: mainSystemHours50,
            main_system_hours_100: mainSystemHours100
        };

        fetch('/calculate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestBody)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const result = data.calculation;
                calculationResultDiv.innerHTML = `
                    <h4>Resultado do Cálculo para ${month}/${year}:</h4>
                    <p><strong>Horas a 50% (deste sistema):</strong> ${result.app_hours_50.toFixed(2)}h</p>
                    <p><strong>Horas a 100% (deste sistema):</strong> ${result.app_hours_100.toFixed(2)}h</p>
                    <hr>
                    <p><strong>TOTAL GERAL (50%):</strong> ${result.final_total_hours_50.toFixed(2)}h</p>
                    <p><strong>TOTAL GERAL (100%):</strong> ${result.final_total_hours_100.toFixed(2)}h</p>
                `;
            } else { calculationResultDiv.innerHTML = `<p class="error">Erro no cálculo.</p>`; }
        })
        .catch(error => {
            console.error('Erro no cálculo:', error);
            calculationResultDiv.innerHTML = `<p class="error">Erro de comunicação com o servidor.</p>`;
        });
    });

    // --- Ponto de Entrada Inicial ---
    loadEmployees();
});

