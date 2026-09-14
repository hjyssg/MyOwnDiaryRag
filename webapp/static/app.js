// 日记回溯 - 前端交互脚本
// 目前提供轻量辅助；主要渲染由后端 Jinja2 完成。
(function () {
    "use strict";

    // 过去的今天：按浏览器本地时区的今天日期默认值提示（供参考）
    document.addEventListener("DOMContentLoaded", function () {
        const today = new Date();
        const month = today.getMonth() + 1;
        const day = today.getDate();
        const pageTitle = document.querySelector(".otd-summary");
        if (pageTitle && !window.location.search) {
            // 无查询参数时已在服务端默认使用今天，此处无需重复设置
            void month;
            void day;
        }
    });
})();
