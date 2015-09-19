# -*- coding: utf-8 -*-
from openerp import models, fields, api
import ftplib
import os
import re
import math
from lxml import etree
import types
import datetime
from constants import *
import logging
_logger = logging.getLogger(__name__)


class cwa_import_module(models.Model):
    _name = 'cwa.import'
        
    def connect_to_ftp(self, address, usr, pwd):
        ftp = ftplib.FTP(address)
        ftp.login(usr, pwd)
        return ftp
    
    def disconnect_from_ftp(self, ftp):
        ftp.quit()
        return True
        
    def download_ftp_files(self, tmp, ftp, todo, done):
        ftp.cwd(done)
        processed_files = ftp.nlst()
        ftp.cwd(todo)
        todo_files = ftp.nlst()
        if not os.path.exists('/tmp/%s' % tmp):
            os.mkdir('/tmp/%s' % tmp)
        for f in todo_files:
            if f not in processed_files:
                ftp.retrbinary("RETR %s" % f, open('/tmp/%s/%s' % (tmp, f), 'wb').write)     
        return True
    
    def move_ftp_files(self, tmp, ftp, todo, done):
        processed_files = os.listdir('/tmp/%s' % tmp)
        for f in processed_files:
            ftp.rename('%s/%s' % (todo, f), '%s/%s' % (done, f))
        return True
    
    def parse_xml_products(self, cr, uid, f):
        product_template_obj = self.pool.get('product.template')
        irmodel_data_obj = self.pool.get('ir.model.data')
        products = []
        product_tags = ['id', 'name', 'list_price', 'standard_price', 'ean13', 'categ_id/id', 
                        'taxes_id', 'supplier_taxes_id', 'available_in_pos', 
                        'uom_id/id', 'uom_po_id/id', 'pos_categ_id/id', 'cwa_product', 
                        'use_deposit', 'select_deposit/id', 'to_weight', 'type']
        root = etree.parse(f).getroot()
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in product_tags:
                    product_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = 0
                # enter prices as floats
                elif item.tag == 'consumentenprijs' or item.tag == 'inkoopprijs': 
                    temp_data[item.tag] = "{0:.2f}".format(float(item.text))
                # enter selection
                elif item.tag in ['proefdiervrij', 'vegetarisch', 'veganistisch', 'rauwe melk']:  
                    if item.text in ['0', '1', '2']:
                        temp_data[item.tag] = item.text
                    else:
                        temp_data[item.tag] = '0'
                # enter boolean
                elif item.tag in ['weegschaalartikel', 'pluartikel', 'wichtartikel']:   
                    if item.text == '1':
                        temp_data[item.tag] = 'true'
                    else:
                        temp_data[item.tag] = 'false'
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()
                
            temp_data['id'] = self.set_external_id(temp_data)
            temp_data['ean13'] = 0 if temp_data['eancode'] == 0 else self.set_ean_code(temp_data['eancode'])
            temp_data['name'] = temp_data['omschrijving']
            temp_data['list_price'] = "{0:.2f}".format(float(temp_data['consumentenprijs']))
            temp_data['standard_price'] = "{0:.2f}".format(float(temp_data['inkoopprijs']))
            temp_data['categ_id/id'] = "cwa_cbl_cat.%s" % temp_data['cblcode']
            temp_data['taxes_id'] = 'Verkopen/omzet hoog' if temp_data['btw'] == '21' else 'Verkopen/omzet laag'
            temp_data['supplier_taxes_id'] = 'BTW te vorderen hoog (inkopen)' if temp_data['btw'] == '21' else 'BTW te vorderen laag (inkopen)'
            temp_data['available_in_pos'] = 'false'
            temp_data['pos_categ_id/id'] = 'cwa_module.cwa_pos_categ_%s' % (temp_data['cblcode'][:5])
            temp_data['cwa_product'] = 'true'
            temp_data['to_weight'] = 'true' if temp_data['weegschaalartikel'] == '1' else 'false'
            temp_data['type'] = 'consu'
            try:
                temp_data['use_deposit'] = 'true' if statiegeld_translations[temp_data['statiegeld']] != 0 else 'false'
                temp_data['select_deposit/id'] = statiegeld_translations[temp_data['statiegeld']] if temp_data['use_deposit'] != 'false' else 0
            except KeyError:
                temp_data['use_deposit'] = 'false'
                temp_data['select_deposit/id'] = 0                
            try:
                temp_data['uom_id/id'] = uom_translations[temp_data['verpakkingce']]
                temp_data['uom_po_id/id'] = uom_translations[temp_data['verpakkingce']]
            except KeyError:
                temp_data['uom_id/id'] = uom_translations['STUKS']
                temp_data['uom_po_id/id'] = uom_translations['STUKS']
        
            temp_list = []
            for tag in product_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append(0)
            
            #check if product already exists in the db
            shared_name_ids = irmodel_data_obj.search(cr, uid, [('name', '=', temp_data['id'])])
            product_exists = False
            for product in products:
                if product[0] == temp_data['id']:
                    product_exists = True
                    break
                
            if product_exists or len(shared_name_ids) > 0:
                continue
            products.append(temp_list)
        return products, product_tags
    
    def parse_xml_supplier_info(self, cr, uid, f):
        root = etree.parse(f).getroot()
        supplier_info = []
        supplier_info_tags = ['id', 'name/id', 'product_tmpl_id/id', 'pos_categ_id', 'min_qty', 'product_code', 'sequence']
        supplier_sequences = {}
        ir_model_obj = self.pool.get('ir.model.data')
        prod_suppl_obj = self.pool.get('product.supplierinfo')
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in supplier_info_tags:
                    supplier_info_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = 0
                # enter prices as floats
                elif item.tag == 'consumentenprijs' or item.tag == 'inkoopprijs': 
                    temp_data[item.tag] = "{0:.2f}".format(float(item.text))
                # enter selection
                elif item.tag in ['proefdiervrij', 'vegetarisch', 'veganistisch', 'rauwe melk']:  
                    if item.text in ['0', '1', '2']:
                        temp_data[item.tag] = item.text.encode('utf-8')
                    else:
                        temp_data[item.tag] = '0'
                # enter boolean
                elif item.tag in ['weegschaalartikel', 'pluartikel', 'wichtartikel']:   
                    if item.text == '1':
                        temp_data[item.tag] = 'true'
                    else:
                        temp_data[item.tag] = 'false'
                else:
                    temp_data[item.tag] = item.text.encode('utf-8').upper()

            temp_data['id'] = 'supplier_info_%s_%s' % (temp_data['leveranciernummer'], temp_data['bestelnummer'])
            temp_data['name/id'] = 'cwa_module.supplier_code_%s' % (temp_data['leveranciernummer'])
            temp_data['product_tmpl_id/id'] = self.set_external_id(temp_data)
            temp_data['pos_categ_id'] = "cwa_module.cwa_pos_categ_%s" % temp_data['cblcode'][:5]
            temp_data['min_qty'] = "{0:.2f}".format(float(temp_data['sve']))
            temp_data['product_code'] = temp_data['bestelnummer']
            sup_info_id = ir_model_obj.search_read(cr, uid, [('name', '=', temp_data['id'])], ['res_id'])
            existing_supplier_info = prod_suppl_obj.search_read(cr, uid, [('id', '=', sup_info_id[0]['res_id'])], ['sequence'])
            existing_product = ir_model_obj.search(cr, uid, [('name', '=', temp_data['product_tmpl_id/id'])])
            if len(existing_supplier_info) > 0:
                temp_data['sequence'] = existing_supplier_info[0]['sequence']
            elif len(existing_product) > 0:
                temp_data['sequence'] = 10
                supplier_sequences[temp_data['product_tmpl_id/id']] = 10
            else:
                try:
                    supplier_sequences[temp_data['product_tmpl_id/id']] += 1
                    temp_data['sequence'] = supplier_sequences[temp_data['product_tmpl_id/id']]
                except KeyError:
                    supplier_sequences[temp_data['product_tmpl_id/id']] = 1
                    temp_data['sequence'] = 1

            temp_list = []
            for tag in supplier_info_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append(0)
            supplier_info.append(temp_list)
        
        return supplier_info, supplier_info_tags
                
                
    def set_external_id(self, data):
        if data['eancode'] == 0:
            return 'product_ex_id_%s_%s' % (data['leveranciernummer'], data['bestelnummer'])
        else:
            return 'product_ex_id_%s' % (data['eancode'])
    
    def set_ean_code(self, ean):
        return sanitize_ean13(ean)
            
    def split_data(self, data):
        split_size = 50
        return [data[x:x+split_size] for x in range(0, len(data), split_size)]
        
    def load_records(self, cr, uid, tags, data, model):
        data = self.split_data(data)
        for d in data:
            for attempt in range(5):
                new_cr = self.pool.cursor()
                x = self.pool.get(model).load(new_cr, uid, tags, d)
                new_cr.commit()
                new_cr.close()
                if len(x['messages']) > 0:
                    _logger.warning("attempt..%s" % attempt)
                    _logger.error(x)
                    continue
                else:
                    _logger.warning("succes..%s" % attempt)
                    break
        return True
    
    def gen_tmp_name(self):
        tmp = 'cwa_import_%s' % datetime.datetime.now().isoformat().replace(':', '').replace('-', '').replace('.', '')
        return tmp

    def write_log(self, log_data):
        with open('error_log.txt', 'a') as f:
            f.write(str(log_data)+'\n\n')
    
    def run(self, cr, uid):
        ''' 
        params[0] = ip address
        params[1] = uid
        params[2] = pwd
        params[3] = todo directory
        params[4] = done directory 
        '''
        pre_time = datetime.datetime.now()
        _logger.warning("Getting arguments")
        params = self.pool['ir.config_parameter'].get_param(cr, uid, 'cwa.import.ftp_info').split(';')
        _logger.warning(params)
        _logger.warning("Connecting to ftp")
        ftp = self.connect_to_ftp(params[0], params[1], params[2]) # returns ftp connection instance
        tmp = self.gen_tmp_name()
        _logger.warning("Downloading files")
        self.download_ftp_files(tmp, ftp, params[3], params[4])
        self.disconnect_from_ftp(ftp)
        _logger.warning("Parsing files")
        for f in os.listdir('/tmp/%s' % tmp):
            _logger.warning("Parsing products")
            product_info = self.parse_xml_products(cr, uid, '/tmp/%s/%s'%(tmp, f))
            _logger.warning("Parsing supplier info")
            supplier_info = self.parse_xml_supplier_info(cr, uid, '/tmp/%s/%s'%(tmp, f))
            _logger.warning("Loading products")
            self.load_records(cr, uid, product_info[1], product_info[0], 'product.template')
            _logger.warning("Loading supplierinfo")
            self.load_records(cr, uid, supplier_info[1], supplier_info[0], 'product.supplierinfo')
        _logger.warning("Moving files")
        ftp = self.connect_to_ftp(params[0], params[1], params[2])
        self.move_ftp_files(tmp, ftp, params[3], params[4])
        ftp.quit()
        post_time = datetime.datetime.now()
        time_delta = post_time - pre_time
        _logger.warning("Done")
        _logger.warning("Took: %s" % str(time_delta))
        return True


class extended_supplierinfo(models.Model):
    _inherit = 'product.supplierinfo'
#     _order = "sequence,id desc"
    
    eancode =           fields.Char('Eancode', help="eancode")
    omschrijving =      fields.Char('Omschrijving', help="omschrijving")
    weegschaalartikel = fields.Boolean('Weegschaalartikel')
    wichtartikel =      fields.Boolean('Wichtartikel')
    pluartikel =        fields.Boolean('Pluartikel')
    inhoud =            fields.Char('Inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('Eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('Verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('Merk', help="merk")
    kwaliteit =         fields.Char('Kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('Btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('Cblcode', help="cblcode")
    leveranciernummer = fields.Char('Leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char('Bestelnummer', help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'proefdiervrij')
    vegetarisch   =     fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'vegetarisch')
    veganistisch =      fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'veganistisch')
    rauwemelk =         fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'rauwemelk')
    inkoopprijs =       fields.Float('Kostprijs', help="inkoopprijs")
    consumentenprijs =  fields.Float('Adviesprijs', help="consumentenprijs")
    ingangsdatum =      fields.Char('Ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('Herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Text('Ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('Statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('Kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Float('Plucode', help="4cijferige plucode.", digits=(4,0 ))
    sve =               fields.Char('Sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('Status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('Keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('Keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('Herkomstregio', help="herkokmstregio")
    aantaldagenhoudbaar=fields.Char('Aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('Bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('Gebruikstips', help="gebruikstips")
    lengte =            fields.Char('Lengte', help="lengte")
    breedte =           fields.Char('Breedte', help="breedte")
    hoogte =            fields.Char('Hoogte', help="hoogte")
    code =              fields.Char('Code', help="code")
    d204 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d204', help="Cacao")
    d209 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d209', help="Glutamaat")
    d210 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d210', help="Gluten")
    d212 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d212', help="Ei")
    d213 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d213', help="Kip")
    d214 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d214', help="Melk")
    d234 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d234', help="Koriander")
    d215 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d215', help="Lactose")
    d239 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d239', help="Lupine")
    d216 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d216', help="Mais")
    d217 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d217', help="Noten")
    d217b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d217b', help="Notenolie")
    d220 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d220', help="Peulvruchten")
    d221 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d221', help="Pinda")
    d221b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d221b', help="Pindaolie")
    d222 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d222', help="Rogge")
    d223 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d223', help="Rundvlees")
    d236 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d236', help="Schaaldieren")
    d235 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d235', help="Selderij")
    d238 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d238', help="Sesam")
    d238b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d238b', help="Sesamolie")
    d225 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d225', help="Soja")
    d226 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d226', help="Soja-olie")
    d228 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d228', help="Sulfiet")
    d230 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d230', help="Tarwe")
    d232 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d232', help="Varkensvlees")
    d237 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d237', help="Vis")
    d240 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d240', help="Wortel")
    d241 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d241', help="Mosterd")
    d242 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d242', help="Weekdieren")
    pos_categ_id =      fields.Char('NOT A REFERENCE', help="Not a reference field, just a char field.")
    
    
class extended_template(models.Model):
    _inherit = 'product.template'

    eancode =           fields.Char('Eancode', help="eancode")
    omschrijving =      fields.Char('Omschrijving', help="omschrijving")
    weegschaalartikel = fields.Boolean('Weegschaalartikel')
    wichtartikel =      fields.Boolean('Wichtartikel')
    pluartikel =        fields.Boolean('Pluartikel')
    inhoud =            fields.Char('Inhoud', help="Inhoud van de verpakking.")
    eenheid =           fields.Char('Eenheid', help="Aanduiding van de inhoud.")
    verpakkingce =      fields.Char('Verpakkingce', help="Verpakking van consumenten eenheid.")
    merk =              fields.Char('Merk', help="merk")
    kwaliteit =         fields.Char('Kwaliteit', help="Kwaliteitsaanduiding")
    btw =               fields.Char('Btw', help="BTW percentage 0, 6 of 21")
    cblcode =           fields.Char('Cblcode', help="cblcode")
    leveranciernummer = fields.Char('Leveranciernummer', help="Identificerend nummer van een leverancier.")
    bestelnummer =      fields.Char('Bestelnummer', help="Bestelnummer van artikel bij leverancier.")
    proefdiervrij =     fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'proefdiervrij')
    vegetarisch   =     fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'vegetarisch')
    veganistisch =      fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'veganistisch')
    rauwemelk =         fields.Selection([('0', 'ONBEKEND'), ('1', 'JA'), ('2', 'NEE')], 'rauwemelk')
    inkoopprijs =       fields.Float('Kostprijs', help="inkoopprijs")
    consumentenprijs =  fields.Float('Verkoopprijs', help="consumentenprijs")
    ingangsdatum =      fields.Char('Ingangsdatum', help="Datum in de vorm eejj-mm-dd")
    herkomst =          fields.Char('Herkomst', help="Land van herkomst in vorm ISO 3166 code.")
    ingredienten =      fields.Text('Ingredienten', help="Beschrijving van de ingredienten.")
    statiegeld =        fields.Char('Statiegeld', help="bedrag")
    kassaomschrijving = fields.Char('Kassaomschrijving', help="Korte omschrijving van het product tbv de kassa")
    plucode =           fields.Char('Plucode', help="4cijferige plucode.", size=4)
    sve =               fields.Char('Sve', help="Standaard verpakkings eenheid bij leverancier.")
    status =            fields.Char('Status', help="Mogelijke waarden: Actief/Non Actief/Gesaneerd")
    keurmerkbio =       fields.Char('Keurmerkbio', help="keurmerkbio")
    keurmerkoverig =    fields.Char('Keurmerkoverig', help="keurmerkoverig")
    herkomstregio =     fields.Char('Herkomstregio', help="herkokmstregio")
    aantaldagenhoudbaar=fields.Char('Aantaldagenhoudbaar', help="aantaldagenhoudbaar")
    bewaartemperatuur = fields.Char('Bewaartemperatuur', help="bewaartemperatuur")
    gebruikstips =      fields.Char('Gebruikstips', help="gebruikstips")
    lengte =            fields.Char('Lengte', help="lengte")
    breedte =           fields.Char('Breedte', help="breedte")
    hoogte =            fields.Char('Hoogte', help="hoogte")
    code =              fields.Char('Code', help="code")
    d204 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d204', help="Cacao")
    d209 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d209', help="Glutamaat")
    d210 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d210', help="Gluten")
    d212 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d212', help="Ei")
    d213 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d213', help="Kip")
    d214 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d214', help="Melk")
    d234 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d234', help="Koriander")
    d215 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d215', help="Lactose")
    d239 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d239', help="Lupine")
    d216 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d216', help="Mais")
    d217 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d217', help="Noten")
    d217b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d217b', help="Notenolie")
    d220 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d220', help="Peulvruchten")
    d221 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d221', help="Pinda")
    d221b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d221b', help="Pindaolie")
    d222 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d222', help="Rogge")
    d223 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d223', help="Rundvlees")
    d236 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d236', help="Schaaldieren")
    d235 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d235', help="Selderij")
    d238 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d238', help="Sesam")
    d238b =             fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d238b', help="Sesamolie")
    d225 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d225', help="Soja")
    d226 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d226', help="Soja-olie")
    d228 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d228', help="Sulfiet")
    d230 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d230', help="Tarwe")
    d232 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d232', help="Varkensvlees")
    d237 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d237', help="Vis")
    d240 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d240', help="Wortel")
    d241 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d241', help="Mosterd")
    d242 =              fields.Selection([('0','ONBEKEND'),('1','AANWEZIG'),('2','NIET AANWEZIG'),('3','MOGELIJK AANWEZIG')],'d242', help="Weekdieren")
    cwa_product =       fields.Boolean('Is CWA product?', default=False, readonly=True)
    
    @api.one
    def _compute_inkoopprijs(self):
        try:
            self.inkoopprijs = self.seller_ids[0].inkoopprijs
        except:
            _logger.warning("Could not set inkoopprijs")

    @api.one        
    def _compute_bestelnummer(self):
        try:
            self.bestelnummer = self.seller_ids[0].bestelnummer
        except:
            _logger.warning("Could not set bestelnummer")

    @api.one       
    def _compute_consumentenprijs(self):
        try:
            self.consumentenprijs = self.seller_ids[0].consumentenprijs
        except:
            _logger.warning("Could not set consumentenprijs")


#############################################################################################################
#                                                                                                           #
#                           These two functions are copied from the product model                           #
#                                                                                                           #
#############################################################################################################
def sanitize_ean13(ean13):                                                                                  
    """Creates and returns a valid ean13 from an invalid one"""                                                          
    ean13 = re.sub("[A-Za-z]","0",ean13);                                                                   
    ean13 = re.sub("[^0-9]","",ean13);                                                                      
    ean13 = ean13[:13]                                                                                      
    if len(ean13) < 13:                                                                                     
        ean13 = ean13 + '0' * (13-len(ean13))                                                                   
    return ean13[:-1] + str(ean_checksum(ean13))                                                                
                                                                                                                
def ean_checksum(eancode):                                                                                  
    """returns the checksum of an ean string of length 13, returns -1 if the string has the wrong length""" 
    if len(eancode) != 13:                                                                                  
        return -1                                                                                           
    oddsum=0                                                                                                
    evensum=0                                                                                               
    total=0                                                                                                 
    eanvalue=eancode                                                                                        
    reversevalue = eanvalue[::-1]                                                                               
    finalean=reversevalue[1:]                                                                               
    
    for i in range(len(finalean)):                                                                          
        if i % 2 == 0:  
            oddsum += int(finalean[i])
        else:
            evensum += int(finalean[i])
    total=(oddsum * 3) + evensum
    
    check = int(10 - math.ceil(total % 10.0)) %10
    return check

#############################################################################################################
