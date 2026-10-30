document.addEventListener("DOMContentLoaded", () => {
  // Mobile navigation.
  const menuToggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", () => sidebar.classList.toggle("sidebar-open"));
  }

  // Dismissible, centred message popups. Remove the backdrop wrapper as well
  // so it can never remain over the page after the final message disappears.
  const removeFlash = (flash) => {
    if (!flash || flash.dataset.closing === "true") return;
    flash.dataset.closing = "true";
    const container = flash.parentElement;
    flash.style.transition = "opacity .22s ease, transform .22s ease";
    flash.style.opacity = "0";
    flash.style.transform = "translateY(12px) scale(.98)";
    window.setTimeout(() => {
      flash.remove();
      if (container && !container.querySelector(".flash")) container.remove();
    }, 240);
  };

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => removeFlash(button.closest(".flash")));
  });
  document.querySelectorAll(".flash-stack .flash, .public-flashes .flash").forEach((flash, index) => {
    window.setTimeout(() => removeFlash(flash), 6500 + index * 300);
  });

  // Dedicated Start Processing popup. It is displayed before the synchronous
  // Flask request begins; the completed/failed flash appears on the returned page.
  const processingModal = document.getElementById("processingModal");
  document.querySelectorAll("form[data-processing-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.processingSubmitted === "true") {
        event.preventDefault();
        return;
      }
      event.preventDefault();
      form.dataset.processingSubmitted = "true";
      const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.dataset.originalText = submitButton.textContent;
        submitButton.textContent = "Processing…";
      }
      if (!processingModal) {
        HTMLFormElement.prototype.submit.call(form);
        return;
      }
      processingModal.classList.add("is-visible");
      processingModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      // Allow the browser to paint the popup before starting the long request.
      window.setTimeout(() => HTMLFormElement.prototype.submit.call(form), 90);
    });
  });

  // Audio upload field.
  const audioInput = document.getElementById("audioFile");
  const fileLabel = document.getElementById("fileLabel");
  const chooseFile = document.getElementById("chooseFile");
  if (audioInput && fileLabel) {
    audioInput.addEventListener("change", () => {
      fileLabel.textContent = audioInput.files.length
        ? audioInput.files[0].name
        : "Choose an audio recording";
    });
  }
  if (audioInput && chooseFile) chooseFile.addEventListener("click", () => audioInput.click());

  // Filter task assignees by the selected team.
  const teamSelect = document.getElementById("teamSelect");
  const assigneeSelect = document.getElementById("assigneeSelect");
  if (teamSelect && assigneeSelect) {
    const filterAssignees = () => {
      [...assigneeSelect.options].forEach((option) => {
        if (!option.value) return;
        option.hidden = option.dataset.team !== teamSelect.value;
        if (option.hidden && option.selected) assigneeSelect.value = "";
      });
    };
    teamSelect.addEventListener("change", filterAssignees);
    filterAssignees();
  }

  // Shared confirmation dialog for account and meeting deletion.
  const confirmModal = document.getElementById("confirmModal");
  if (confirmModal) {
    const title = document.getElementById("confirmModalTitle");
    const message = document.getElementById("confirmModalMessage");
    const icon = document.getElementById("confirmModalIcon");
    const cancel = document.getElementById("confirmModalCancel");
    const accept = document.getElementById("confirmModalAccept");
    let pendingForm = null;
    let previousFocus = null;

    const closeConfirm = (restoreFocus = true) => {
      confirmModal.classList.remove("is-visible");
      confirmModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      const focusTarget = previousFocus;
      pendingForm = null;
      previousFocus = null;
      if (restoreFocus && focusTarget && document.contains(focusTarget)) {
        focusTarget.focus({ preventScroll: true });
      }
    };

    document.querySelectorAll("form[data-confirm-title]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (form.dataset.confirmed === "true") return;
        event.preventDefault();
        pendingForm = form;
        previousFocus = document.activeElement;
        title.textContent = form.dataset.confirmTitle || "Please confirm";
        message.textContent = form.dataset.confirmMessage || "Are you sure you want to continue?";
        if (icon) icon.textContent = form.dataset.confirmIcon || "⚠️";
        accept.textContent = form.dataset.confirmLabel || "Confirm";
        confirmModal.classList.add("is-visible");
        confirmModal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        accept.focus();
      });
    });

    cancel.addEventListener("click", () => closeConfirm(true));
    confirmModal.addEventListener("click", (event) => {
      if (event.target === confirmModal) closeConfirm(true);
    });
    accept.addEventListener("click", () => {
      if (!pendingForm) return;
      const form = pendingForm;
      form.dataset.confirmed = "true";
      closeConfirm(false);
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else HTMLFormElement.prototype.submit.call(form);
    });
    document.addEventListener("keydown", (event) => {
      if (!confirmModal.classList.contains("is-visible")) return;
      if (event.key === "Escape") closeConfirm(true);
      if (event.key === "Tab") {
        const controls = [cancel, accept];
        if (event.shiftKey && document.activeElement === controls[0]) {
          event.preventDefault();
          controls[1].focus();
        } else if (!event.shiftKey && document.activeElement === controls[1]) {
          event.preventDefault();
          controls[0].focus();
        }
      }
    });
  }
});
