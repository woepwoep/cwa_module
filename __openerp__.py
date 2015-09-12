{
    'name': 'cwa module',
    'description': 'cwa module voor producten.',
    'author': 'Open2bizz',
    'application': True,
    'depends': ['sale', 'l10n_nl', 'point_of_sale'],
    'data': ['view.xml', 
             'data/res_partner.xml', 
             'data/product.uom.csv', 
             'data/product.category.csv', 
             'data/ir.cron.csv', 
             'data/pos_categories.xml',
             'data/statiegeld_products.xml',
             ],
    'init': ['data/ir.config_parameter.xml',]
}