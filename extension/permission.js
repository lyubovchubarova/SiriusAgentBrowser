document.addEventListener('DOMContentLoaded', () => {
    const allowBtn = document.getElementById('allow-btn');
    const successMsg = document.getElementById('success-msg');
    const errorMsg = document.getElementById('error-msg');

    allowBtn.addEventListener('click', () => {
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then((stream) => {
                // Останавливаем поток, разрешение уже получено
                stream.getTracks().forEach(track => track.stop());
                
                allowBtn.style.display = 'none';
                successMsg.style.display = 'block';
                
                // Закрываем вкладку через 2 секунды
                setTimeout(() => { window.close(); }, 2000);
            })
            .catch((err) => {
                console.error(err);
                errorMsg.style.display = 'block';
                errorMsg.innerText = "Ошибка: " + err.message;
            });
    });
});