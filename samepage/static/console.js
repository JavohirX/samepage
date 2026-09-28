(function () {
  var form = document.querySelector("[data-console]");
  if (!form) return;
  var status = document.querySelector("[data-save-status]");
  var fields = Array.prototype.slice.call(form.querySelectorAll("[data-criterion]"));
  var index = 0;

  function payload() {
    var criteria = {};
    fields.forEach(function (field) {
      criteria[field.getAttribute("data-criterion")] = field.value;
    });
    var comment = form.querySelector("[name=comment]");
    return { criteria: criteria, comment: comment ? comment.value : "" };
  }

  function save() {
    if (!status) return;
    status.textContent = "saving…";
    fetch(form.getAttribute("data-autosave"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRFToken": form.getAttribute("data-csrf")
      },
      body: JSON.stringify(payload())
    }).then(function (response) {
      if (!response.ok) {
        return response.json().then(function (problem) {
          status.textContent = "could not save: " + (problem.title || response.status);
        });
      }
      status.textContent = "saved";
    }).catch(function () {
      status.textContent = "could not save: network";
    });
  }

  fields.forEach(function (field, fieldIndex) {
    field.addEventListener("focus", function () { index = fieldIndex; });
    field.addEventListener("change", save);
  });
  var comment = form.querySelector("[name=comment]");
  if (comment) comment.addEventListener("change", save);

  document.addEventListener("keydown", function (event) {
    if (event.target && event.target.tagName === "TEXTAREA") return;
    if (event.key >= "1" && event.key <= "5") {
      fields[index].value = event.key;
      fields[index].dispatchEvent(new Event("change"));
      event.preventDefault();
    } else if (event.key === "j" || event.key === "J") {
      index = Math.min(fields.length - 1, index + 1);
      fields[index].focus();
    } else if (event.key === "k" || event.key === "K") {
      index = Math.max(0, index - 1);
      fields[index].focus();
    }
  });
})();
