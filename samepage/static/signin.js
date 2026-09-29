// The sign-in screen: show what each role lands on, and fill the form from a demo account.
(function () {
  var form = document.getElementById("signin-form");
  var note = document.getElementById("role-note");
  function showNote() {
    var checked = form.querySelector("input[name=role]:checked");
    if (checked) note.textContent = checked.parentNode.getAttribute("data-note");
  }
  form.addEventListener("change", showNote);
  showNote();
  document.querySelectorAll(".accounts button").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll(".accounts button").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      button.setAttribute("aria-pressed", "true");
      document.getElementById("signin-email").value = button.getAttribute("data-email");
      document.getElementById("signin-password").value = "samepage-demo";
      var radio = form.querySelector("input[name=role][value=" + button.getAttribute("data-role") + "]");
      if (radio) radio.checked = true;
      showNote();
      document.getElementById("signin-submit").focus();
    });
  });
})();
