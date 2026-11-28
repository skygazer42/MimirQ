import zhCNMessages from './zh-CN'

// The application currently exposes zh-CN only; retain new navigation copy for its English catalog.
const enMessages = {
  ...zhCNMessages,
  Navbar: {
    ...zhCNMessages.Navbar,
    items: { ...zhCNMessages.Navbar.items, enterpriseOntology: 'Enterprise ontology' },
  },
  CommandMenu: {
    ...zhCNMessages.CommandMenu,
    modules: {
      ...zhCNMessages.CommandMenu.modules,
      ontology: {
        label: 'Enterprise ontology',
        description: 'Model, validate and run enterprise business definitions',
        keywords: ['ontology', 'enterprise ontology', 'modeling', 'rules', 'actions'],
      },
    },
  },
} as const

export default enMessages
