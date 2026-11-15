const exam = document.querySelector('#exam');
const score = document.querySelector('#score');
const questions = exam.querySelectorAll('fieldset');

exam.addEventListener('submit', event => {
  event.preventDefault();
  let correct = 0;
  for (const question of questions) {
    const matches = question.querySelector('input:checked')?.value === question.dataset.answer;
    correct += Number(matches);
    const feedback = question.querySelector('.feedback');
    feedback.textContent = (matches ? '정답. ' : '오답. ') + question.dataset.explanation;
    feedback.hidden = false;
  }
  score.textContent = `${questions.length}문제 중 ${correct}문제 정답`;
});
exam.addEventListener('reset', () => {
  score.textContent = '';
  for (const question of questions) question.querySelector('.feedback').hidden = true;
});
