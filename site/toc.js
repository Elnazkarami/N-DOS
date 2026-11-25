/* Builds a contents list from the headings already on the page.
 *
 * No library, no CDN, and nothing happens on a page with too few sections to
 * be worth one -- a table of contents with two entries is furniture, not
 * navigation. */
(function () {
  "use strict";
  var aside = document.querySelector(".toc");
  var main = document.getElementById("content");
  if (!aside || !main) return;

  var headings = [].slice.call(main.querySelectorAll("h2[id]"));
  if (headings.length < 4) return;

  var list = document.createElement("ol");
  headings.forEach(function (heading) {
    var item = document.createElement("li");
    var link = document.createElement("a");
    link.href = "#" + heading.id;
    link.textContent = heading.textContent.replace(/\s+/g, " ").trim();
    item.appendChild(link);
    list.appendChild(item);
  });

  var title = document.createElement("h2");
  title.textContent = "On this page";
  aside.appendChild(title);
  aside.appendChild(list);
  aside.hidden = false;
  document.body.classList.add("has-toc");

  /* Mark the section being read, if the browser can tell us cheaply. */
  if (!("IntersectionObserver" in window)) return;
  var links = {};
  [].slice.call(aside.querySelectorAll("a")).forEach(function (a) {
    links[a.getAttribute("href").slice(1)] = a;
  });
  var seen = new Set();
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) seen.add(entry.target.id);
      else seen.delete(entry.target.id);
    });
    headings.forEach(function (h) {
      if (links[h.id]) links[h.id].classList.remove("here");
    });
    for (var i = 0; i < headings.length; i++) {
      if (seen.has(headings[i].id)) {
        if (links[headings[i].id]) links[headings[i].id].classList.add("here");
        break;
      }
    }
  }, { rootMargin: "0px 0px -70% 0px" });
  headings.forEach(function (h) { observer.observe(h); });
})();
