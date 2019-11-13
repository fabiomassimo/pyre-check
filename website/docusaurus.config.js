/**
 * Copyright (c) 2017-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

const siteConfig = {
  title: 'Pyre',
  tagline: 'A performant type-checker for Python 3',
  url: 'https://pyre-check.org',
  baseUrl: '/',
  organizationName: 'facebook',
  projectName: 'pyre-check',
  scripts: ['https://buttons.github.io/buttons.js'],
  // // TODO(T29078584): Add Algolia search
  themeConfig: {
    navbar: {
      logo: {
        alt: 'Pyre',
        src: 'img/integrated_logo_light.png',
      },
      links: [
        { to: 'docs/installation', label: 'Getting Started' },
        { to: 'docs/overview', label: 'Documentation' },
        { href: 'https://github.com/facebook/pyre-check', label: 'GitHub' },
      ],
    },
    footer: {
      style: 'dark',
      logo: {
        alt: 'Facebook Open Source Logo',
        src: 'https://docusaurus.io/img/oss_logo.png',
      },
      links: [
        {
          title: 'Docs',
          items: [
            { to: 'docs/installation', label: 'Installation' },
            { to: 'docs/overview', label: 'Overview' },
          ]
        },
        {
          title: 'Community',
          items: [
            { href: 'https://code.facebook.com/projects/', label: 'Open Source Projects' },
            { href: 'https://github.com/facebook/pyre-check', label: 'Contribute to Pyre' },
          ]
        },
        {
          title: 'Social',
          items: [
            { href: 'https://github.com/facebook/', label: 'Github' },
            { href: 'https://twitter.com/fbOpenSource', label: 'Twitter' },
          ]
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Facebook, Inc.`,
    },
  },
  favicon: 'img/favicon.ico',
  presets: [
    [
      '@docusaurus/preset-classic',
      {
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
        },
        theme: {
          customCss: require.resolve('./css/custom.css'),
        },
      },
    ],
  ],
};

module.exports = siteConfig;
