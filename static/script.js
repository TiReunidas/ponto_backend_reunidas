document.addEventListener('DOMContentLoaded', function() {
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
        fetch('/employees')
        .then(response => response.json())
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

