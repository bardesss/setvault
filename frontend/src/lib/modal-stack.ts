/** Open modals, oldest first. Only the last one may react to Escape/Tab. */
const stack: symbol[] = [];

export function pushModal(id: symbol): void {
  if (!stack.includes(id)) stack.push(id);
}

export function removeModal(id: symbol): void {
  const i = stack.indexOf(id);
  if (i >= 0) stack.splice(i, 1);
}

export function isTopModal(id: symbol): boolean {
  return stack.length > 0 && stack[stack.length - 1] === id;
}
