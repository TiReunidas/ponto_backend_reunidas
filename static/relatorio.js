document.addEventListener('DOMContentLoaded', function() {
    const employeeSelect = document.getElementById('employee-select');
    const generateBtn = document.getElementById('generate-report-btn');
    const selectAllBtn = document.getElementById('select-all-btn');
    const exportBtn = document.getElementById('export-csv-btn');
    const tableBody = document.getElementById('report-table-body');
    const loader = document.getElementById('loader');

    let reportDataCache = []; // Para guardar os dados para exportação

    // 1. Carregar a lista de funcionários ao abrir a página
    function loadEmployees() {
        fetch('/employees') // Supondo que você tenha um endpoint que lista os funcionários
            .then(response => response.json())
            .then(data => {
                data.employees.forEach(emp => {
                    const option = document.createElement('option');
                    option.value = emp.employee_id;
                    option.textContent = emp.name;
                    employeeSelect.appendChild(option);
                });
            });
    }

    // 2. Lógica do botão "Selecionar Todos"
    selectAllBtn.addEventListener('click', () => {
        for (let i = 0; i < employeeSelect.options.length; i++) {
            employeeSelect.options[i].selected = true;
        }
    });

    // 3. Lógica principal para gerar o relatório
    generateBtn.addEventListener('click', () => {
        const startDate = document.getElementById('start-date').value;
        const endDate = document.getElementById('end-date').value;
        const selectedIds = Array.from(employeeSelect.selectedOptions).map(opt => opt.value);

        if (!startDate || !endDate) {
            alert('Por favor, selecione uma data de início e fim.');
            return;
        }
        
        loader.style.display = 'block';
        tableBody.innerHTML = ''; // Limpa resultados antigos
        exportBtn.style.display = 'none';

        fetch('/report', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                employee_ids: selectedIds,
                start_date: startDate,
                end_date: endDate
            })
        })
        .then(response => response.json())
        .then(result => {
            loader.style.display = 'none';
            if (result.status === 'success') {
                reportDataCache = result.data; // Salva os dados
                populateTable(reportDataCache);
                if(reportDataCache.length > 0) {
                    exportBtn.style.display = 'inline-block';
                }
            } else {
                alert('Ocorreu um erro ao gerar o relatório.');
            }
        });
    });

    // 4. Função para preencher a tabela com os dados
    function populateTable(data) {
        data.forEach(item => {
            const total50 = item.main_system_hours_50 + item.new_system_hours_50;
            const total100 = item.main_system_hours_100 + item.new_system_hours_100;

            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${item.employee_id}</td>
                <td>${item.main_system_hours_50.toFixed(2)}</td>
                <td>${item.main_system_hours_100.toFixed(2)}</td>
                <td>${item.new_system_hours_50.toFixed(2)}</td>
                <td>${item.new_system_hours_100.toFixed(2)}</td>
                <td><strong>${total50.toFixed(2)}</strong></td>
                <td><strong>${total100.toFixed(2)}</strong></td>
            `;
            tableBody.appendChild(row);
        });
    }
    
    // Inicializar a página
    loadEmployees();
});