// Restore preferences before the stylesheet paints. Disabled storage is tolerated.
try {
 const allowed=['light','grey','solarized','midnight','black'];
 const theme=localStorage.getItem('freia-theme');
 document.documentElement.dataset.theme=allowed.includes(theme)?theme:'light';
 const plan=localStorage.getItem('freia-plan-theme');
 document.documentElement.dataset.plan=['auto','light','dark'].includes(plan)?plan:'auto';
}catch{document.documentElement.dataset.theme='light';document.documentElement.dataset.plan='auto';}
