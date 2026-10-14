export const pictureDimensions = ['320x224', '320x184', '320x176', '320x168', '320x144'];

export function availablePictureDimensions(width, height) {
  return width === 288 && height === 200
    ? ['320x224', '320x184', '288x200', '320x176', '320x168', '320x144']
    : pictureDimensions;
}

export function selectPictureDimensions(width, height, pixelAspect = 1) {
  const options = availablePictureDimensions(width, height);
  const exact = `${width}x${height}`;
  if (options.includes(exact)) return exact;
  const sourceAspect = width * pixelAspect / height;
  // Compare visible proportions after the H40 pixel aspect correction.
  return options.reduce((best, option) => {
    const error = value => {
      const [w, h] = value.split('x').map(Number);
      return Math.abs(Math.log((w * 32 / 35 / h) / sourceAspect));
    };
    return error(option) < error(best) ? option : best;
  }, options[0]);
}
