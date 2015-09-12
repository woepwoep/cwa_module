{
    'name': 'cwa module',
    'description': 'cwa module voor producten.',
    'author': 'Open2bizz',
    'application': True,
    'depends': ['product', 'point_of_sale', 'account'],
    'data': ['view.xml', 'data/res_partner.xml', 'data/product.uom.csv', 'data/product.category.csv', 'data/ir.cron.csv', 'data/ir.config_parameter.xml']
}