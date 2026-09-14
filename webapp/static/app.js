// 我的日记 - 前端交互脚本
// 主要停留在：多篇日记列表页的内联展开/收起（手风琴效果）。
(function () {
    "use strict";

    var DiaryUI = {
        // 懒加载某篇日记的完整内容（仅首次展开时请求一次）
        loadContent: function (row, box) {
            if (box.dataset.loaded) {
                return Promise.resolve();
            }
            var id = row.dataset.id;
            return fetch("/api/entries/" + id, { headers: { "Accept": "application/json" } })
                .then(function (r) {
                    if (!r.ok) {
                        throw new Error("HTTP " + r.status);
                    }
                    return r.json();
                })
                .then(function (data) {
                    // 使用 textContent 直接赋值，天然规避 XSS，并依靠 CSS pre-wrap 保留换行
                    box.textContent = data.content || "(无内容)";
                    box.dataset.loaded = "1";
                })
                .catch(function () {
                    box.textContent = "(内容加载失败)";
                    box.dataset.loaded = "1";
                });
        },

        // 展开 / 收起（手风琴式内联阅读，不跳转页面）
        toggle: function (head) {
            var row = head.closest && head.closest(".expandable");
            if (!row) {
                return;
            }
            var detail = row.querySelector(".entry-detail");
            var icon = head.querySelector(".expand-icon");
            if (detail.hidden) {
                var self = this;
                this.loadContent(row, detail.querySelector(".entry-full-content")).then(function () {
                    detail.hidden = false;
                    row.classList.add("open");
                    if (icon) {
                        icon.textContent = "▴";
                    }
                    detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
                    // 关闭同一容器内其他已展开的条目（手风琴）
                    var container = row.closest(".entry-list") || row.parentElement;
                    var others = container.querySelectorAll(".expandable.open");
                    others.forEach(function (o) {
                        if (o !== row) {
                            o.classList.remove("open");
                            var od = o.querySelector(".entry-detail");
                            var oi = o.querySelector(".expand-icon");
                            if (od) {
                                od.hidden = true;
                            }
                            if (oi) {
                                oi.textContent = "▾";
                            }
                        }
                    });
                });
            } else {
                detail.hidden = true;
                row.classList.remove("open");
                if (icon) {
                    icon.textContent = "▾";
                }
            }
        }
    };

    window.DiaryUI = DiaryUI;
})();
