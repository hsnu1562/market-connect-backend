const authDialog = document.getElementById("auth-dialog");

if (authDialog) {
    const authRoutes = {
        Tenant: {
            google: authDialog.dataset.tenantGoogle,
            title: "登入後預約",
            copy: "攤位資訊保持公開；送出預約時才需要帳戶。",
        },
        Landlord: {
            google: authDialog.dataset.landlordGoogle,
            title: "登入後刊登攤位",
            copy: "瀏覽不需登入；建立攤位與出租時段時才需要帳戶。",
        },
    };

    function authUrl(path, nextPath) {
        const url = new URL(path, window.location.origin);
        if (nextPath) url.searchParams.set("next", nextPath);
        return url.pathname + url.search;
    }

    document.querySelectorAll("[data-auth-role]").forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            if (typeof authDialog.showModal !== "function") return;
            event.preventDefault();
            const route = authRoutes[trigger.dataset.authRole];
            if (!route) return;

            const nextPath = trigger.dataset.authNext || "";
            document.getElementById("auth-dialog-title").textContent = route.title;
            document.getElementById("auth-dialog-copy").textContent = route.copy;
            document.getElementById("auth-google-link").href = authUrl(route.google, nextPath);
            authDialog.showModal();
        });
    });

    authDialog.addEventListener("click", (event) => {
        if (event.target === authDialog) authDialog.close();
    });
}
