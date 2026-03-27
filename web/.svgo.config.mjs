const config = {
  multipass: true,
  plugins: [
    'preset-default',
    {
      name: 'removeViewBox',
      active: false,
    },
    {
      name: 'removeDimensions',
      active: true,
    },
  ],
}

export default config
