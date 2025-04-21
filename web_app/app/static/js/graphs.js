document.addEventListener('DOMContentLoaded', function () {
    const dbSizeChartElement = document.getElementById('dbSizeChart');
    if (!dbSizeChartElement || !window.dbSizes) return;

    const labels = window.dbSizes.map(item => item.name);
    const data = window.dbSizes.map(item => item.size_mb);

    // Každý sloupec jinou barvou
    const backgroundColors = labels.map((_, i) => {
        const hue = (i * 360 / labels.length) % 360;
        return `hsl(${hue}, 70%, 60%)`;
    });

    const ctx = dbSizeChartElement.getContext('2d');

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Velikost databáze (MB)',
                data: data,
                backgroundColor: backgroundColors,
                borderColor: '#444',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                title: {
                    display: true,
                    text: 'Velikost databází'
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Název databáze'
                    },
                    ticks: {
                        autoSkip: false,
                        maxRotation: 30,
                        minRotation: 15
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Velikost v MB'
                    }
                }
            }
        }
    });
});

