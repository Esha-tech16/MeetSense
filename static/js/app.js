document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");
  if (toggle && sidebar) toggle.addEventListener("click", () => sidebar.classList.toggle("sidebar-open"));
  document.querySelectorAll(".flash-close").forEach(btn => btn.addEventListener("click", () => btn.closest(".flash").remove()));
  const input = document.getElementById("audioFile");
  const label = document.getElementById("fileLabel");
  const choose = document.getElementById("chooseFile");
  if (input && label) input.addEventListener("change", () => {
    label.textContent = input.files.length ? input.files[0].name : "Choose an audio recording";
  });
  if (input && choose) choose.addEventListener("click", () => input.click());
  const team = document.getElementById("teamSelect");
  const assignee = document.getElementById("assigneeSelect");
  if (team && assignee) {
    const filter = () => {
      [...assignee.options].forEach(o => {
        if (!o.value) return;
        o.hidden = o.dataset.team !== team.value;
        if (o.hidden && o.selected) assignee.value = "";
      });
    };
    team.addEventListener("change", filter); filter();
  }
});
