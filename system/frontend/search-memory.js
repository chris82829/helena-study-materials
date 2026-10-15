export function createMemory(random = Math.random) {
  const cards = ['study', 'work', 'idea', 'study', 'work', 'idea'];
  for (let i = cards.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }
  return {cards, open:[], matched:[], turns:0};
}

export function flipMemory(state, index) {
  if (!Number.isInteger(index) || index < 0 || index >= state.cards.length
      || state.open.length === 2 || state.open.includes(index) || state.matched.includes(index)) return state;
  const open = [...state.open, index];
  if (open.length === 2 && state.cards[open[0]] === state.cards[open[1]]) {
    return {...state, open:[], matched:[...state.matched, ...open], turns:state.turns + 1};
  }
  return {...state, open, turns:state.turns + (open.length === 2 ? 1 : 0)};
}
