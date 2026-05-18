setTimeout(() => {
    const alerts = document.querySelectorAll(".alert");

    alerts.forEach(alert => {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
        bsAlert.close();
    });
}, 4000);


const themeToggle = document.getElementById("themeToggle");

if (localStorage.getItem("theme") === "dark") {
    document.body.classList.add("dark-mode");
    if (themeToggle) {
        themeToggle.innerText = "☀️ Light";
    }
}

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        document.body.classList.toggle("dark-mode");

        if (document.body.classList.contains("dark-mode")) {
            localStorage.setItem("theme", "dark");
            themeToggle.innerText = "☀️ Light";
        } else {
            localStorage.setItem("theme", "light");
            themeToggle.innerText = "🌙 Dark";
        }
    });
}