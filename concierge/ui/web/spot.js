// The Spot (spot.html). Python opens it with what's highlighted and the buttons
// that fit (spot.open), runs the job when one is picked, and puts the answer back
// into the program the user was in. This page only shows them.
//
// Text is always set with textContent, never as HTML.

window.spot = (() => {
  const $ = (id) => document.getElementById(id);
  const api = () => window.pywebview.api;

  let text = ""; // what was highlighted
  let editable = false; // whether the answer can replace it
  let answer = "";
  let busy = false;
  let ticket = 0; // a newer opening makes an older answer stale

  function fit() {
    requestAnimationFrame(() => api().fit(Math.ceil($("card").getBoundingClientRect().height)));
  }

  function el(tag, className, words) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = words;
    return node;
  }

  // The answer can go back three ways. With nothing highlighted it is typed at the cursor.
  function ways() {
    if (!text) return [["insert", "Type it here"], ["copy", "Copy"]];
    if (editable) return [["replace", "Replace"], ["below", "Insert below"], ["copy", "Copy"]];
    return [["copy", "Copy"], ["replace", "Replace"]];
  }

  function showAnswer(words, seconds) {
    answer = words;
    $("answer").className = "answer";
    $("answer").textContent = words;
    const [first, second, third] = ways();
    for (const [id, way] of [["primary", first], ["second", second], ["third", third]]) {
      $(id).hidden = !way;
      if (way) {
        $(id).textContent = way[1];
        $(id).dataset.how = way[0];
      }
    }
    $("took").textContent = `On this computer · ${seconds} s`;
    $("after").hidden = false;
    $("primary").focus();
  }

  async function run(action, ask = "") {
    if (busy) return;
    busy = true;
    const mine = ++ticket;
    document.querySelectorAll(".chip").forEach((chip) => {
      chip.disabled = true;
      chip.classList.toggle("now", chip.dataset.id === action);
    });
    $("after").hidden = true;
    $("answer").hidden = false;
    $("answer").className = "answer working";
    $("answer").textContent = "Working on it...";
    fit();
    const began = Date.now();
    const reply = (await api().run(action, text, ask)) || {};
    if (mine !== ticket) return;
    busy = false;
    document.querySelectorAll(".chip").forEach((chip) => (chip.disabled = false));
    if (reply.error) {
      $("answer").className = "answer failed";
      $("answer").textContent = reply.error;
    } else {
      showAnswer(reply.text || "", ((Date.now() - began) / 1000).toFixed(1));
    }
    fit();
  }

  // Called from Python each time the Spot opens.
  function open(data) {
    ticket += 1;
    busy = false;
    text = data.text || "";
    editable = Boolean(data.editable);
    answer = "";
    $("where").textContent = data.app ? `in ${data.app}` : "";
    $("picked").hidden = !text;
    $("picked").textContent = text ? `"${text}"` : "";
    $("answer").hidden = true;
    $("after").hidden = true;
    $("ask").value = "";
    $("ask").placeholder = text ? "Or tell me what to do with it..." : "What should I write for you?";
    $("actions").replaceChildren(...(data.actions || []).map((action, index) => {
      const chip = el("button", "chip", action.words);
      chip.type = "button";
      chip.dataset.id = action.id;
      chip.title = `${action.words} (${index + 1})`;
      chip.addEventListener("click", () => run(action.id));
      return chip;
    }));
    fit();
    setTimeout(() => (text && data.actions && data.actions.length ? document.querySelector(".chip") : $("ask")).focus(), 30);
  }

  function putBack(how) {
    if (answer) api().put_back(how, answer);
  }

  for (const id of ["primary", "second", "third"]) {
    $(id).addEventListener("click", () => putBack($(id).dataset.how));
  }

  $("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const ask = $("ask").value.trim();
    if (ask) run("ask", ask);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      api().close();
    } else if (/^[1-6]$/.test(event.key) && document.activeElement !== $("ask")) {
      const chip = document.querySelectorAll(".chip")[Number(event.key) - 1];
      if (chip) chip.click();
    }
  });

  // Clicking anywhere else closes it, like a menu.
  window.addEventListener("blur", () => {
    if (!busy) api().close();
  });

  return { open };
})();
