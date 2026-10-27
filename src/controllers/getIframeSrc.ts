export function getIframeSrc(path: string, trialId: string, iframeId: string) {
  const hashIndex = path.indexOf('#');
  const pathAndQuery = hashIndex === -1 ? path : path.slice(0, hashIndex);
  const hash = hashIndex === -1 ? '' : path.slice(hashIndex);
  const separator = pathAndQuery.includes('?')
    ? (pathAndQuery.endsWith('?') || pathAndQuery.endsWith('&') ? '' : '&')
    : '?';
  const controllerParams = new URLSearchParams({
    trialid: trialId,
    id: iframeId,
  });

  return `${pathAndQuery}${separator}${controllerParams.toString()}${hash}`;
}
